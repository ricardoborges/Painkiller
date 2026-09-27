"""Autopilot: runs a project's whole backlog and publishes the result.

O fluxo manual (despachar tarefa a tarefa, aprovar cada merge) faz sentido
para um analista. Para quem só descreveu o que queria, o que importa é
"construa e coloque no ar". Este módulo encadeia o orquestrador:

    próxima tarefa pronta -> dispatch -> testes passaram? merge -> repete
    ... até acabar -> publica (Coolify)

Ele para e devolve o controle ao usuário em duas situações: o agente fez uma
pergunta (AWAITING_ANALYST, código 42) ou uma tarefa falhou. Respondida a
pergunta ou refeita a tarefa, basta acionar de novo — ele retoma de onde parou,
porque o estado que importa está nos status das tarefas, não aqui.
"""

import asyncio
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from painkiller.core.domain.models import Task, TaskStatus
from painkiller.core.ports.issue_tracker import IssueTrackerPort
from painkiller.engine.orchestrator import PainkillerOrchestrator

logger = logging.getLogger(__name__)

#: Tarefas que o piloto pode pegar por conta própria.
RUNNABLE = (TaskStatus.BACKLOG, TaskStatus.READY)


class AutopilotState(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PUBLISHING = "PUBLISHING"
    DONE = "DONE"
    # Precisa do usuário: pergunta pendente ou tarefa falhada.
    PAUSED = "PAUSED"
    FAILED = "FAILED"


class AutopilotRun(BaseModel):
    project_id: str
    state: AutopilotState = AutopilotState.IDLE
    current_task_id: Optional[str] = None
    current_task_title: Optional[str] = None
    completed: int = 0
    total: int = 0
    message: str = ""
    publish: bool = True
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None

    @property
    def active(self) -> bool:
        return self.state in (AutopilotState.RUNNING, AutopilotState.PUBLISHING)


class ProjectAutopilot:
    """One background loop per project, kept in-process like the analysis sessions."""

    def __init__(self, orchestrator: PainkillerOrchestrator, tracker: IssueTrackerPort):
        self.orchestrator = orchestrator
        self.tracker = tracker
        self.runs: dict[str, AutopilotRun] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def status(self, project_id: str) -> AutopilotRun:
        return self.runs.get(project_id) or AutopilotRun(project_id=project_id)

    async def start(self, project_id: str, publish: bool = True) -> AutopilotRun:
        current = self.runs.get(project_id)
        if current and current.active:
            return current

        project = await self.tracker.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        tasks = await self.tracker.list_tasks(project_id)
        if not tasks:
            raise RuntimeError("O backlog está vazio: conclua a análise inicial antes de construir.")

        run = AutopilotRun(
            project_id=project_id,
            state=AutopilotState.RUNNING,
            total=len(tasks),
            completed=sum(1 for t in tasks if t.status == TaskStatus.COMPLETED),
            publish=publish and self.orchestrator.can_publish(),
            message="Iniciando.",
        )
        self.runs[project_id] = run
        self._tasks[project_id] = asyncio.create_task(self._loop(run))
        return run

    async def _loop(self, run: AutopilotRun) -> None:
        try:
            while True:
                tasks = await self.tracker.list_tasks(run.project_id)
                run.total = len(tasks)
                run.completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)

                if any(t.status == TaskStatus.AWAITING_ANALYST for t in tasks):
                    stuck = next(t for t in tasks if t.status == TaskStatus.AWAITING_ANALYST)
                    self._pause(run, stuck, "O agente fez uma pergunta e precisa da sua resposta.")
                    return

                nxt = pick_next(tasks)
                if nxt is None:
                    break

                run.current_task_id = nxt.id
                run.current_task_title = nxt.title
                run.message = f"Construindo: {nxt.title}"
                task = await self.orchestrator.dispatch_task(nxt.id)

                if task.status == TaskStatus.IN_REVIEW:
                    run.message = f"Incorporando: {task.title}"
                    task = await self.orchestrator.merge_task(task.id)
                    run.completed += 1
                elif task.status == TaskStatus.AWAITING_ANALYST:
                    self._pause(run, task, "O agente fez uma pergunta e precisa da sua resposta.")
                    return
                else:
                    self._pause(
                        run,
                        task,
                        "Uma etapa falhou. Veja o detalhe no backlog e use 'Repetir' para tentar de novo.",
                        state=AutopilotState.FAILED,
                    )
                    return

            tasks = await self.tracker.list_tasks(run.project_id)
            run.completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
            run.current_task_id = None
            run.current_task_title = None

            leftovers = [t for t in tasks if t.status != TaskStatus.COMPLETED]
            if leftovers:
                # Nada mais é executável, mas sobrou coisa: dependência falhada
                # ou tarefa em revisão que o piloto não abriu.
                run.state = AutopilotState.PAUSED
                titles = ", ".join(t.title for t in leftovers[:3])
                run.message = f"Restaram etapas que não puderam avançar sozinhas: {titles}."
                run.finished_at = datetime.now(timezone.utc)
                return

            if run.publish:
                run.state = AutopilotState.PUBLISHING
                run.message = "Publicando a aplicação."
                project = await self.orchestrator.publish_project(run.project_id)
                url = project.deployment.url if project.deployment else None
                run.message = f"Publicado em {url}." if url else "Publicação iniciada."
            else:
                run.message = "Todas as etapas foram concluídas."

            run.state = AutopilotState.DONE
            run.finished_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.exception(f"Autopilot for {run.project_id} aborted")
            run.state = AutopilotState.FAILED
            run.message = str(e)
            run.finished_at = datetime.now(timezone.utc)

    @staticmethod
    def _pause(run: AutopilotRun, task: Task, message: str, state: AutopilotState = AutopilotState.PAUSED) -> None:
        run.state = state
        run.current_task_id = task.id
        run.current_task_title = task.title
        run.message = message
        run.finished_at = datetime.now(timezone.utc)


def pick_next(tasks: list[Task]) -> Optional[Task]:
    """First runnable task whose dependencies are all completed, in creation order."""
    done = {t.id for t in tasks if t.status == TaskStatus.COMPLETED}
    for task in sorted(tasks, key=lambda t: t.created_at):
        if task.status not in RUNNABLE:
            continue
        if all(dep in done for dep in task.dependencies):
            return task
    return None
