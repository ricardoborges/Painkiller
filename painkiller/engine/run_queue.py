"""Server-side "Executar Todas": runs a session's tasks one after another.

A fila vivia num laço do navegador: fechar a aba (ou o notebook dormir) parava
tudo. Aqui ela roda no processo da API, uma por projeto, e a UI só a observa.
O estado fica em memória: um restart a encerra, e a tarefa que rodava sai de
RUNNING por `PainkillerOrchestrator.recover_interrupted`.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from painkiller.core.domain.models import Project, SessionStatus, Task, TaskStatus
from painkiller.core.i18n import project_language, tr
from painkiller.core.ports.issue_tracker import IssueTrackerPort
from painkiller.engine.orchestrator import PainkillerOrchestrator

logger = logging.getLogger(__name__)

# Motivos do estado da fila; a UI traduz cada um (chaves `backlog.queue.*`).
STARTING = "starting"
RUNNING = "running"
MERGING = "merging"
PAUSED = "paused"
ALL_DONE = "all_done"
QUESTION = "question"
BLOCKED = "blocked"
FAILED = "failed"
RUN_FAILED = "run_failed"
MERGE_FAILED = "merge_failed"
BUDGET = "budget"

#: Paradas que pedem a atenção de quem saiu da tela.
NOTIFIED = {ALL_DONE, QUESTION, FAILED, RUN_FAILED, MERGE_FAILED, BUDGET}

ALREADY_RUNNING = "Esta tarefa já está em execução."


class QueueBusyError(RuntimeError):
    """The project already has a queue running."""


class QueueSessionError(RuntimeError):
    """The session is unknown or belongs to another project."""


class SessionClosedError(RuntimeError):
    """The session was finalized: its branches are gone."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class QueueRun:
    project_id: str
    session_id: Optional[str]
    running: bool = True
    reason: str = STARTING
    task_id: Optional[str] = None
    task_title: str = ""
    blocked_by: list[str] = field(default_factory=list)
    detail: str = ""
    pause_requested: bool = False
    started_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    job: Optional[asyncio.Task] = None

    def view(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "pausing": self.running and self.pause_requested,
            "session_id": self.session_id,
            "reason": self.reason,
            "task_id": self.task_id,
            "task_title": self.task_title,
            "blocked_by": list(self.blocked_by),
            "detail": self.detail,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


IDLE: dict[str, Any] = {
    "running": False, "pausing": False, "session_id": None, "reason": None, "task_id": None,
    "task_title": "", "blocked_by": [], "detail": "", "started_at": None, "updated_at": None,
}


def execution_order(tasks: list[Task]) -> list[Task]:
    """Planning order with every dependency before its dependents (same rule as the backlog UI)."""
    by_id = {t.id: t for t in tasks}
    ordered: list[Task] = []
    visited: set[str] = set()

    def visit(task: Task, stack: frozenset[str]) -> None:
        if task.id in visited or task.id in stack:
            return
        for dep_id in task.dependencies:
            dep = by_id.get(dep_id)
            if dep is not None and dep_id not in visited:
                visit(dep, stack | {task.id})
        visited.add(task.id)
        ordered.append(task)

    for task in sorted(tasks, key=lambda t: t.created_at):
        visit(task, frozenset())
    return ordered


def notification_text(project: Project, run: QueueRun) -> Optional[tuple[str, str]]:
    """(subject, body) of the e-mail for a queue stop, in the project's language; None when silent."""
    if run.reason not in NOTIFIED:
        return None
    locale = project_language(project)
    title = run.task_title
    if run.reason == ALL_DONE:
        subject = tr("Painkiller: {project} terminou as tarefas", locale=locale, project=project.name)
        body = tr("Todas as tarefas da sessão foram concluídas e incorporadas.", locale=locale)
    elif run.reason == QUESTION:
        subject = tr("Painkiller: {project} espera a sua resposta", locale=locale, project=project.name)
        body = tr(
            "O agente tem uma dúvida na tarefa \"{title}\" e a execução está parada até você responder.",
            locale=locale, title=title,
        )
    elif run.reason == BUDGET:
        subject = tr("Painkiller: {project} atingiu o orçamento", locale=locale, project=project.name)
        body = tr(
            "A execução foi pausada antes da tarefa \"{title}\": o orçamento do projeto foi atingido.",
            locale=locale, title=title,
        )
    else:
        subject = tr("Painkiller: {project} parou em uma tarefa", locale=locale, project=project.name)
        body = tr("A execução parou: a tarefa \"{title}\" não foi concluída.", locale=locale, title=title)
    return subject, body


class RunQueueService:
    """One background queue per project over `PainkillerOrchestrator.dispatch_task`."""

    def __init__(
        self,
        tracker: IssueTrackerPort,
        orchestrator: PainkillerOrchestrator,
        over_budget: Optional[Callable[[Project], Awaitable[bool]]] = None,
        notify: Optional[Callable[[Project, QueueRun], Awaitable[None]]] = None,
    ):
        self.tracker = tracker
        self.orchestrator = orchestrator
        self.over_budget = over_budget
        self.notify = notify
        self._runs: dict[str, QueueRun] = {}

    def state(self, project_id: str) -> dict[str, Any]:
        run = self._runs.get(project_id)
        return run.view() if run else dict(IDLE)

    async def start(self, project: Project, session_id: Optional[str] = None) -> dict[str, Any]:
        current = self._runs.get(project.id)
        if current and current.running:
            raise QueueBusyError("A fila deste projeto já está em execução.")
        # Um despacho avulso em andamento ocupa a árvore de trabalho do projeto.
        self.orchestrator.ensure_project_free(project.id)
        if session_id:
            session = await self.tracker.get_session(session_id)
            if not session or session.project_id != project.id:
                raise QueueSessionError("Sessão não encontrada")
            if session.status == SessionStatus.COMPLETED:
                raise SessionClosedError("Esta sessão já foi encerrada.")
        run = QueueRun(project_id=project.id, session_id=session_id)
        self._runs[project.id] = run
        run.job = asyncio.create_task(self._run(run, project))
        return run.view()

    def pause(self, project_id: str) -> dict[str, Any]:
        """Stop after the task that is running; it is not interrupted."""
        run = self._runs.get(project_id)
        if run and run.running:
            run.pause_requested = True
            run.updated_at = _utcnow()
        return self.state(project_id)

    async def resume_after_answer(self, task: Task) -> None:
        """Pick the queue back up once the question that stopped it was answered and the task passed."""
        run = self._runs.get(task.project_id)
        if not run or run.running or run.reason != QUESTION or run.task_id != task.id:
            return
        if task.status != TaskStatus.COMPLETED:
            return
        project = await self.tracker.get_project(task.project_id)
        if project is None:
            return
        try:
            await self.start(project, run.session_id)
        except Exception as e:
            logger.info(f"Fila de {task.project_id} não retomada após a resposta: {e}")

    async def shutdown(self) -> None:
        jobs = [run.job for run in self._runs.values() if run.job and not run.job.done()]
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)

    def _set(self, run: QueueRun, reason: str, task: Optional[Task] = None) -> None:
        run.reason = reason
        if task is not None:
            run.task_id, run.task_title = task.id, task.title
        run.updated_at = _utcnow()

    async def _stop(self, run: QueueRun, project: Project, reason: str, detail: str = "") -> None:
        run.running = False
        run.detail = detail
        self._set(run, reason)
        if self.notify is not None and reason in NOTIFIED:
            try:
                await self.notify(project, run)
            except Exception as e:
                logger.warning(f"Aviso da fila de {project.id} não enviado: {e}")

    async def _mark_in_sprint(self, run: QueueRun) -> None:
        if not run.session_id:
            return
        try:
            session = await self.tracker.get_session(run.session_id)
            if session and session.status == SessionStatus.BACKLOG:
                session.status = SessionStatus.IN_SPRINT
                session.updated_at = _utcnow()
                await self.tracker.update_session(session)
        except Exception as e:
            logger.debug(f"Sessão {run.session_id} não passou para IN_SPRINT: {e}")

    async def _run(self, run: QueueRun, project: Project) -> None:
        try:
            await self._mark_in_sprint(run)
            while True:
                if run.pause_requested:
                    return await self._stop(run, project, PAUSED)
                everything = await self.tracker.list_tasks(project.id)
                by_id = {t.id: t for t in everything}
                scope = [t for t in everything if not run.session_id or t.session_id == run.session_id]
                pending = [t for t in execution_order(scope) if t.status != TaskStatus.COMPLETED]
                if not pending:
                    return await self._stop(run, project, ALL_DONE)
                task = pending[0]
                self._set(run, RUNNING, task)
                run.blocked_by = []

                if task.status == TaskStatus.IN_REVIEW:
                    self._set(run, MERGING)
                    try:
                        await self.orchestrator.merge_task(task.id)
                    except Exception as e:
                        return await self._stop(run, project, MERGE_FAILED, str(e))
                    continue
                if task.status == TaskStatus.AWAITING_ANALYST:
                    return await self._stop(run, project, QUESTION)
                if task.status == TaskStatus.RUNNING:
                    return await self._stop(run, project, RUN_FAILED, ALREADY_RUNNING)

                # Mesma regra do orquestrador: dependência ausente também trava.
                blockers = [
                    by_id[d].title if d in by_id else d
                    for d in task.dependencies
                    if d not in by_id or by_id[d].status != TaskStatus.COMPLETED
                ]
                if blockers:
                    run.blocked_by = blockers
                    return await self._stop(run, project, BLOCKED)

                if self.over_budget is not None and await self._is_over_budget(project):
                    return await self._stop(run, project, BUDGET)

                try:
                    updated = await self.orchestrator.dispatch_task(task.id)
                except Exception as e:
                    return await self._stop(run, project, RUN_FAILED, str(e))

                if updated.status == TaskStatus.AWAITING_ANALYST:
                    return await self._stop(run, project, QUESTION)
                if updated.status != TaskStatus.COMPLETED:
                    # Parada pelo usuário no meio da fila: é pausa, não falha a avisar.
                    return await self._stop(run, project, PAUSED if run.pause_requested else FAILED)
        except asyncio.CancelledError:
            run.running = False
            raise
        except Exception as e:
            logger.exception(f"Fila do projeto {project.id} interrompida")
            await self._stop(run, project, RUN_FAILED, str(e))

    async def _is_over_budget(self, project: Project) -> bool:
        try:
            return bool(await self.over_budget(project))
        except Exception as e:
            # Sem conseguir calcular o gasto, a fila segue: o teto é uma proteção, não um requisito.
            logger.debug(f"Orçamento de {project.id} não verificado: {e}")
            return False
