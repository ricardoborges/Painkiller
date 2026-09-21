"""Painkiller Task Execution Engine & State Machine."""

import logging
from typing import Optional, Any
from painkiller.core.domain.models import Task, TaskStatus, Project
from painkiller.core.ports.issue_tracker import IssueTrackerPort
from painkiller.core.ports.sandbox import SandboxPort
from painkiller.core.ports.git import GitPort

logger = logging.getLogger(__name__)


class PainkillerOrchestrator:
    """Coordinates task execution, git branches, docker containers, and status transitions."""

    def __init__(
        self,
        tracker: IssueTrackerPort,
        sandbox: SandboxPort,
        git: GitPort,
        vcs: Optional[Any] = None,
    ):
        self.tracker = tracker
        self.sandbox = sandbox
        self.git = git
        self.vcs = vcs

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

        # Ensure feature branch
        branch_name = task.assigned_branch or f"feature/{task.id}"
        await self.git.create_branch(project.repo_path, branch_name, project.default_branch)
        task.assigned_branch = branch_name

        # Mark as running
        await self.tracker.update_task_status(task.id, TaskStatus.RUNNING)

        # Build prompt instructions
        instructions = self._build_task_instructions(task, project)

        # Execute container
        result = await self.sandbox.run_task(task, project.repo_path, instructions)

        # Handle exit codes
        if result.exit_code == 42 and result.clarification:
            # Paused for clarification
            await self.tracker.create_clarification(
                task.id,
                result.clarification.question,
                result.clarification.context_summary,
            )
            await self.tracker.update_task_status(task.id, TaskStatus.AWAITING_ANALYST)
            await self.tracker.add_comment(
                task.id,
                author="system",
                comment=f"🤖 Paused for clarification: {result.clarification.question}",
            )
        elif result.exit_code == 0:
            # Run test verification
            test_code, test_out = await self.git.run_tests(project.repo_path)
            if test_code == 0:
                await self.git.commit_wip(project.repo_path, f"feat: implement {task.title}")
                try:
                    await self.git.push(project.repo_path, branch_name)
                except Exception as push_err:
                    logger.debug(f"Git push skipped or failed: {push_err}")

                await self.tracker.update_task_status(task.id, TaskStatus.IN_REVIEW)
                await self.tracker.add_comment(
                    task.id,
                    author="system",
                    comment="✅ Task completed and tests passed. Ready for review.",
                )
            else:
                await self.tracker.update_task_status(task.id, TaskStatus.FAILED)
                await self.tracker.add_comment(
                    task.id,
                    author="system",
                    comment=f"❌ Tests failed after agent execution:\n{test_out}",
                )
        else:
            await self.tracker.update_task_status(task.id, TaskStatus.FAILED)
            await self.tracker.add_comment(
                task.id,
                author="system",
                comment=f"❌ Agent execution failed with exit code {result.exit_code}:\n{result.logs}",
            )

        updated_task = await self.tracker.get_task(task.id)
        return updated_task or task

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
            "\n## Protocolo de Dúvidas:\n"
            "Se você encontrar qualquer ambiguidade ou precisar de esclarecimento do analista, "
            "NÃO adivinhe. Execute o comando no shell:\n"
            "painkiller ask \"<sua dúvida>\" --context \"<arquivo e linha>\"\n"
            "Isso salvará suas alterações e pausará o contêiner de forma limpa."
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

