"""Painkiller Task Execution Engine & State Machine."""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Any
from painkiller.core.domain.models import (
    AgentEvent,
    AgentEventType,
    ExecutionResult,
    Project,
    SessionStatus,
    Task,
    TaskStatus,
    UsageRecord,
    UsageSource,
)
from painkiller.core.ports.issue_tracker import IssueTrackerPort
from painkiller.core.ports.sandbox import SandboxPort
from painkiller.core.ports.git import GitPort
from painkiller.core.ports.usage_ledger import UsageLedgerPort
from painkiller.core.usage import parse_task_usage
from painkiller.engine.task_activity import TaskActivityHub

logger = logging.getLogger(__name__)

#: Tempo máximo de uma execução de tarefa. Tarefas com testes de navegador ou
#: `npm install` passam fácil dos 10 min do padrão antigo.
DEFAULT_TASK_TIMEOUT = 1800

#: Quanto do log bruto vai no comentário de falha (o espelho do Gitea ainda o
#: recolhe num <details>). O log inteiro de uma execução passa de centenas de KB.
FAILURE_LOG_TAIL = 20_000

STOPPED_MESSAGE = (
    "Execução interrompida pelo usuário. O trabalho parcial ficou na branch {branch}: "
    "use Repetir para continuar de onde parou."
)


def task_timeout_seconds() -> int:
    """`PAINKILLER_TASK_TIMEOUT` in seconds, falling back to the default on garbage."""
    try:
        value = int(os.environ.get("PAINKILLER_TASK_TIMEOUT", "") or DEFAULT_TASK_TIMEOUT)
    except ValueError:
        return DEFAULT_TASK_TIMEOUT
    return value if value > 0 else DEFAULT_TASK_TIMEOUT


class PainkillerOrchestrator:
    """Coordinates task execution, git branches, docker containers, and status transitions."""

    def __init__(
        self,
        tracker: IssueTrackerPort,
        sandbox: SandboxPort,
        git: GitPort,
        vcs: Optional[Any] = None,
        usage: Optional[UsageLedgerPort] = None,
        activity: Optional[TaskActivityHub] = None,
    ):
        self.tracker = tracker
        self.sandbox = sandbox
        self.git = git
        self.vcs = vcs
        self.usage = usage
        self.activity = activity or TaskActivityHub()
        # Tarefas cuja interrupção foi pedida durante uma execução deste processo:
        # o _dispatch registra a falha como interrupção, não como código 137.
        self._stop_requested: set[str] = set()
        # Tarefas cujo contêiner foi morto por "Abreviar testes" e devem reiniciar.
        self._restart_requested: set[str] = set()

    def _note(self, task_id: str, text: str) -> None:
        """Tell whoever watches the task what the orchestrator itself is doing."""
        self.activity.publish(task_id, AgentEvent(type=AgentEventType.SYSTEM, text=text))

    async def dispatch_task(self, task_id: str) -> Task:
        """Dispatch a task to the sandbox environment and update lifecycle accordingly."""
        task = await self.tracker.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        project = await self.tracker.get_project(task.project_id)
        if not project:
            raise ValueError(f"Project {task.project_id} not found")
        if not project.api_key:
            raise RuntimeError(
                "Este projeto não tem chave de API cadastrada. Abra Editar projeto e informe a chave "
                "do provedor do harness antes de despachar tarefas."
            )

        # Verify dependency constraints
        if task.dependencies:
            for dep_id in task.dependencies:
                dep_task = await self.tracker.get_task(dep_id)
                if not dep_task or dep_task.status != TaskStatus.COMPLETED:
                    raise RuntimeError(f"Cannot run task {task.id}: dependency {dep_id} is not completed")

        self._stop_requested.discard(task.id)
        self._restart_requested.discard(task.id)
        self.activity.start(task.id)
        try:
            updated = await self._dispatch(task, project)
            # "Abreviar testes" mata o contêiner e pede um reinício: roda de novo
            # aqui mesmo, para que a requisição aberta pela UI receba o desfecho final.
            while updated is None:
                self._restart_requested.discard(task.id)
                task = await self.tracker.get_task(task.id) or task
                self._note(task.id, "Reiniciando o agente sem testes, a pedido do analista")
                updated = await self._dispatch(task, project, resuming=True)
            return updated
        finally:
            self.activity.finish(task.id)
            self._stop_requested.discard(task.id)
            self._restart_requested.discard(task.id)

    async def _dispatch(self, task: Task, project: Project, resuming: bool = False) -> Optional[Task]:
        """Run the task once; None means the run was killed to be restarted."""
        # Uma nova tentativa roda na mesma branch, por cima do que ficou da anterior.
        retrying = resuming or task.status == TaskStatus.FAILED
        # Ensure feature branch
        branch_name = task.assigned_branch or f"feature/{task.id}"
        await self.git.create_branch(project.repo_path, branch_name, project.default_branch)
        task.assigned_branch = branch_name

        # Mark as running and persist assigned branch
        await self.tracker.update_task_status(
            task.id,
            TaskStatus.RUNNING,
            assigned_branch=branch_name,
        )

        # Build prompt instructions
        instructions = self._build_task_instructions(task, project, retrying=retrying)

        # Execute container
        self._note(task.id, f"Iniciando contêiner na branch {branch_name}")
        timeout = task_timeout_seconds()
        result = await self.sandbox.run_task(
            task,
            project.repo_path,
            instructions,
            timeout_seconds=timeout,
            on_event=self.activity.publisher(task.id, asyncio.get_running_loop()),
            harness=project.harness,
            api_key=project.api_key,
            model=project.model,
        )
        self._note(task.id, f"Agente encerrou com código {result.exit_code}")
        await self._record_usage(task, result)

        if task.id in self._restart_requested and result.exit_code not in (0, 42):
            return None

        # O analista pode ter abreviado os testes enquanto o agente rodava.
        fresh = await self.tracker.get_task(task.id)
        skip_tests = bool(task.skip_tests or (fresh is not None and fresh.skip_tests))

        # Handle exit codes
        if result.exit_code == 42 and result.clarification:
            # Paused for clarification
            await self.tracker.create_clarification(
                task.id,
                result.clarification.question,
                result.clarification.context_summary,
            )
            await self.tracker.update_task_status(
                task.id,
                TaskStatus.AWAITING_ANALYST,
                assigned_branch=branch_name,
            )
            await self.tracker.add_comment(
                task.id,
                author="system",
                comment=f"🤖 Paused for clarification: {result.clarification.question}",
            )
        elif result.exit_code == 0:
            if skip_tests:
                self._note(task.id, "Testes abreviados pelo analista: suíte não executada")
                test_code, test_out = 0, ""
            else:
                self._note(task.id, "Executando a suíte de testes do repositório")
                test_code, test_out = await self.git.run_tests(project.repo_path)
            if test_code in (0, 5):
                await self.git.commit_wip(project.repo_path, f"feat: implement {task.title}")
                try:
                    await self.git.push(project.repo_path, branch_name)
                except Exception as push_err:
                    logger.debug(f"Git push skipped or failed: {push_err}")

                # Auto-merge é a regra do Painkiller: aprovada e incorporada na branch padrão
                self._note(task.id, f"Incorporando branch na {project.default_branch}")
                code_m, out_m = await self.git.merge_branch(
                    project.repo_path,
                    source_branch=branch_name,
                    target_branch=project.default_branch,
                )
                if code_m == 0:
                    try:
                        await self.git.push(project.repo_path, project.default_branch)
                    except Exception as e:
                        logger.debug(f"Push after merge skipped or failed: {e}")

                    await self.tracker.update_task_status(task.id, TaskStatus.COMPLETED)
                    comment = f"✅ Tarefa concluída, testada e incorporada na {project.default_branch}."
                    if skip_tests:
                        comment += " Testes abreviados pelo analista: o teste manual fica por conta dele."
                    elif test_code == 5 or "Sem testes" in test_out:
                        comment += " (Sem testes coletados no repositório)"
                    await self.tracker.add_comment(
                        task.id,
                        author="system",
                        comment=comment,
                    )
                else:
                    await self.tracker.update_task_status(
                        task.id,
                        TaskStatus.FAILED,
                        assigned_branch=branch_name,
                        error=f"Falha ao realizar merge na {project.default_branch}:\n{out_m}",
                    )
                    await self.tracker.add_comment(
                        task.id,
                        author="system",
                        comment=f"❌ Falha no auto-merge da branch {branch_name} na {project.default_branch}:\n{out_m}",
                    )
            else:
                await self.tracker.update_task_status(
                    task.id,
                    TaskStatus.FAILED,
                    assigned_branch=branch_name,
                    error=test_out,
                )
                await self.tracker.add_comment(
                    task.id,
                    author="system",
                    comment=f"❌ Tests failed after agent execution:\n{test_out}",
                )
        else:
            if task.id in self._stop_requested:
                error_msg = STOPPED_MESSAGE.format(branch=branch_name)
            else:
                error_msg = self._describe_failure(result, timeout, branch_name)
            await self.tracker.update_task_status(
                task.id,
                TaskStatus.FAILED,
                assigned_branch=branch_name,
                error=error_msg,
            )
            tail = (result.logs or "")[-FAILURE_LOG_TAIL:]
            await self.tracker.add_comment(
                task.id,
                author="system",
                comment=f"{error_msg}\n\nFinal do log do agente:\n{tail}" if tail.strip() else error_msg,
            )

        updated_task = await self.tracker.get_task(task.id)
        return updated_task or task

    async def _record_usage(self, task: Task, result: ExecutionResult) -> None:
        """Book what the agent says it spent, whatever the exit code — a failed run still costs."""
        if self.usage is None:
            return
        parsed = parse_task_usage(result.logs)
        if parsed is None:
            return
        input_tokens, output_tokens, cost, model = parsed
        try:
            await self.usage.record_usage(
                UsageRecord(
                    source=UsageSource.TASK,
                    model=model or os.environ.get("PAINKILLER_AGENT_MODEL", os.environ.get("PAINKILLER_LLM_MODEL", "gemini-3.8-flash")),
                    project_id=task.project_id,
                    task_id=task.id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    reported_cost_usd=cost,
                )
            )
        except Exception as e:
            logger.debug(f"Usage not recorded for {task.id}: {e}")

    async def reply_clarification(self, clarification_id: str, answer: str) -> Task:
        """Provide answer to a paused clarification and resume the task."""
        clar = await self.tracker.resolve_clarification(clarification_id, answer)
        await self.tracker.add_comment(
            clar.task_id,
            author="analyst",
            comment=f"💬 Analyst clarified: {answer}",
        )
        return await self.dispatch_task(clar.task_id)

    async def stop_task(self, task_id: str) -> None:
        """Stop a running task by killing its container, and make sure its status moves.

        When this process is running the dispatch, killing the container is
        enough: `_dispatch` wakes up and records the interruption. Otherwise —
        typically after an API restart — nothing would ever leave RUNNING, so
        the status is set here.
        """
        live = self._is_live(task_id)
        if live:
            self._stop_requested.add(task_id)
            self._restart_requested.discard(task_id)
        self._note(task_id, "Interrompendo execução da tarefa a pedido do usuário")
        await self.sandbox.stop_task(task_id)
        if live:
            return

        task = await self.tracker.get_task(task_id)
        if task is None or task.status != TaskStatus.RUNNING:
            return
        branch = task.assigned_branch or f"feature/{task.id}"
        message = STOPPED_MESSAGE.format(branch=branch)
        await self.tracker.update_task_status(
            task.id,
            TaskStatus.FAILED,
            assigned_branch=branch,
            error=message,
        )
        await self.tracker.add_comment(task.id, author="system", comment=message)

    def _is_live(self, task_id: str) -> bool:
        """Whether this process is running a dispatch of the task right now."""
        run = self.activity.get(task_id)
        return run is not None and not run.done

    async def abbreviate_tests(self, task_id: str) -> bool:
        """Waive the agent's tests: the analyst takes on manual testing and its risks.

        The agent runs one-shot, so there is no way to tell it mid-turn. A live
        run is killed and restarted on the same branch with the no-tests prompt
        (returns True); otherwise the flag just applies to the next dispatch.
        """
        task = await self.tracker.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        if task.status == TaskStatus.COMPLETED:
            raise RuntimeError("A tarefa já foi concluída.")

        if not task.skip_tests:
            await self.tracker.set_task_skip_tests(task_id, True)
            await self.tracker.add_comment(
                task_id,
                author="analyst",
                comment="⏩ Testes abreviados: o analista assume o teste manual e os riscos.",
            )

        if task_id in self._stop_requested:
            return False
        if not self._is_live(task_id):
            # Órfã de um restart: libera a tarefa para a UI despachá-la de novo.
            if task.status == TaskStatus.RUNNING:
                await self.stop_task(task_id)
            return False
        self._restart_requested.add(task_id)
        self._note(task_id, "Testes abreviados pelo analista: reiniciando o agente sem testes")
        await self.sandbox.stop_task(task_id)
        return True

    @staticmethod
    def _describe_failure(result: ExecutionResult, timeout: int, branch: str) -> str:
        """Short pt-BR account of a failed run — the full log goes in the comment, not here."""
        if result.timed_out:
            minutes = max(1, round(timeout / 60))
            head = (
                f"O agente excedeu o tempo limite de {minutes} min e o contêiner foi encerrado. "
                f"O trabalho parcial ficou na branch {branch}: use Repetir para continuar de onde parou "
                f"ou aumente PAINKILLER_TASK_TIMEOUT."
            )
        else:
            head = f"O agente encerrou com código {result.exit_code}."
        if result.summary:
            return f"{head}\n\nÚltima mensagem do agente:\n{result.summary}"
        return head

    def _build_task_instructions(self, task: Task, project: Project, retrying: bool = False) -> str:
        instructions = [
            f"# Tarefa: {task.title}",
        ]
        # No topo e com precedência explícita: a spec e o plano do superpowers
        # mandam fazer TDD e verificar tudo, e o agente os lê no meio da tarefa.
        if task.skip_tests:
            instructions.append(
                "\n## PRIORIDADE MÁXIMA: testes abreviados pelo analista\n"
                "O analista vai testar manualmente e assume os riscos. Esta instrução prevalece sobre "
                "a spec, o plano, os critérios de aceitação e qualquer skill (inclusive "
                "test-driven-development e verification-before-completion):\n"
                "- NÃO leia, crie, edite nem execute arquivos de teste (tests/, test_*, *.test.*, *.spec.*).\n"
                "- NÃO rode nada para conferir comportamento: nada de pytest, npm test, navegador, "
                "`node -e`, `python -c` ou scripts de verificação.\n"
                "- Critérios de aceitação que falam de testes ou verificação ficam a cargo do analista.\n"
                "- Leia só o necessário para implementar, implemente, faça o commit e encerre."
            )
        instructions.append(f"\n## Descrição:\n{task.description}")
        if retrying:
            instructions.append(
                "\n## Execução anterior interrompida:\n"
                "Uma tentativa anterior desta tarefa falhou ou foi interrompida nesta mesma branch. "
                "Antes de começar, inspecione o estado atual (git status, git log, arquivos já criados) "
                "e continue a partir do que já existe em vez de refazer do zero."
            )
        if task.target_files:
            instructions.append("\n## Arquivos Alvo:")
            for f in task.target_files:
                instructions.append(f"- {f}")

        if task.acceptance_criteria:
            instructions.append("\n## Critérios de Aceitação:")
            for c in task.acceptance_criteria:
                instructions.append(f"- {c}")

        if task.skip_tests:
            guidelines = (
                "\n## Diretrizes de Execução:\n"
                "1. Não carregue skills de teste nem de verificação; se seguir um plano, pule os passos de teste.\n"
                "2. Implemente o código solicitado com qualidade, sem testes (veja PRIORIDADE MÁXIMA acima).\n"
                "3. Faça commit de suas alterações no repositório git local com uma mensagem descritiva (ex: feat: ... ou fix: ...).\n"
            )
        else:
            guidelines = (
                "\n## Diretrizes de Execução:\n"
                "1. Utilize as skills e boas práticas do plugin Superpowers disponíveis (como test-driven-development e executing-plans).\n"
                "2. Implemente o código solicitado com qualidade e crie ou execute testes quando aplicável.\n"
                "3. Faça commit de suas alterações no repositório git local com uma mensagem descritiva (ex: feat: ... ou fix: ...).\n"
            )
        instructions.append(
            guidelines
            + "\n## Protocolo de Dúvidas:\n"
            "Se você encontrar qualquer ambiguidade crítica ou precisar de esclarecimento do analista, "
            "NÃO adivinhe. Execute o comando no shell:\n"
            "painkiller ask \"<sua dúvida>\" --context \"<arquivo e linha>\"\n"
            "Isso salvará suas alterações e pausará a execução de forma limpa."
        )

        return "\n".join(instructions)

    async def merge_task(self, task_id: str) -> Task:
        """Merge a reviewed task branch into the project default branch and push to remote."""
        task = await self.tracker.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        project = await self.tracker.get_project(task.project_id)
        if not project:
            raise ValueError(f"Project {task.project_id} not found")

        branch_name = task.assigned_branch or f"feature/{task.id}"
        # A branch da tarefa continua viva no Gitea após o merge: o botão
        # "Testar" de cada tarefa concluída faz deploy dela no Coolify.
        try:
            await self.git.push(project.repo_path, branch_name)
        except Exception as e:
            logger.debug(f"Push of {branch_name} before merge skipped or failed: {e}")

        code, out = await self.git.merge_branch(
            project.repo_path,
            source_branch=branch_name,
            target_branch=project.default_branch,
        )
        if code != 0:
            raise RuntimeError(f"Falha ao realizar merge da branch {branch_name} na {project.default_branch}: {out}")

        try:
            await self.git.push(project.repo_path, project.default_branch)
        except Exception as e:
            logger.debug(f"Push after merge skipped or failed: {e}")

        await self.tracker.update_task_status(task.id, TaskStatus.COMPLETED)
        await self.tracker.add_comment(
            task.id,
            author="analyst",
            comment=f"🚀 Tarefa aprovada e incorporada na branch principal ({project.default_branch}).",
        )
        updated_task = await self.tracker.get_task(task.id)
        return updated_task or task

    async def finalize_session(self, session_id: str) -> list[str]:
        """Mark a session COMPLETED and delete the branches of its merged tasks.

        Only COMPLETED tasks lose their branch: those are already merged into
        the default branch. Anything else keeps it, since it may be migrated to
        the next session and continue from there. Returns the deleted branches.
        """
        session = await self.tracker.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        project = await self.tracker.get_project(session.project_id)
        if not project:
            raise ValueError(f"Project {session.project_id} not found")

        deleted: list[str] = []
        tasks = await self.tracker.list_tasks(session.project_id, session_id=session_id)
        for task in tasks:
            if task.status != TaskStatus.COMPLETED:
                continue
            branch = task.assigned_branch or f"feature/{task.id}"
            try:
                code, out = await self.git.delete_branch(
                    project.repo_path, branch, merged_into=project.default_branch
                )
            except Exception as e:
                code, out = 1, str(e)
            if code == 0:
                deleted.append(branch)
            else:
                logger.warning(f"Branch {branch} mantida ao finalizar a sessão {session_id}: {out}")

        if session.status != SessionStatus.COMPLETED:
            session.status = SessionStatus.COMPLETED
            session.updated_at = datetime.now(timezone.utc)
            await self.tracker.update_session(session)
        return deleted

