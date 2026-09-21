"""Painkiller Task Execution Engine & State Machine."""

import asyncio
import logging
import os
from typing import Optional, Any
from painkiller.core.domain.models import (
    AgentEvent,
    AgentEventType,
    ExecutionResult,
    Project,
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

        # Verify dependency constraints
        if task.dependencies:
            for dep_id in task.dependencies:
                dep_task = await self.tracker.get_task(dep_id)
                if not dep_task or dep_task.status != TaskStatus.COMPLETED:
                    raise RuntimeError(f"Cannot run task {task.id}: dependency {dep_id} is not completed")

        self.activity.start(task.id)
        try:
            return await self._dispatch(task, project)
        finally:
            self.activity.finish(task.id)

    async def _dispatch(self, task: Task, project: Project) -> Task:
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
        instructions = self._build_task_instructions(task, project)

        # Execute container
        self._note(task.id, f"Iniciando contêiner na branch {branch_name}")
        result = await self.sandbox.run_task(
            task,
            project.repo_path,
            instructions,
            on_event=self.activity.publisher(task.id, asyncio.get_running_loop()),
        )
        self._note(task.id, f"Agente encerrou com código {result.exit_code}")
        await self._record_usage(task, result)

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
            # Run test verification
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
                    if test_code == 5 or "Sem testes" in test_out:
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
            error_msg = f"❌ Agent execution failed with exit code {result.exit_code}:\n{result.logs}"
            await self.tracker.update_task_status(
                task.id,
                TaskStatus.FAILED,
                assigned_branch=branch_name,
                error=error_msg,
            )
            await self.tracker.add_comment(
                task.id,
                author="system",
                comment=error_msg,
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

    def _build_task_instructions(self, task: Task, project: Project) -> str:
        instructions = [
            f"# Tarefa: {task.title}",
            f"\n## Descrição:\n{task.description}",
        ]
        if task.target_files:
            instructions.append("\n## Arquivos Alvo:")
            for f in task.target_files:
                instructions.append(f"- {f}")

        if task.acceptance_criteria:
            instructions.append("\n## Critérios de Aceitação:")
            for c in task.acceptance_criteria:
                instructions.append(f"- {c}")

        instructions.append(
            "\n## Diretrizes de Execução:\n"
            "1. Utilize as skills e boas práticas do plugin Superpowers disponíveis (como test-driven-development e executing-plans).\n"
            "2. Implemente o código solicitado com qualidade e crie ou execute testes quando aplicável.\n"
            "3. Faça commit de suas alterações no repositório git local com uma mensagem descritiva (ex: feat: ... ou fix: ...).\n"
            "\n## Protocolo de Dúvidas:\n"
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

