"""Painkiller Task Execution Engine & State Machine."""

import logging
from datetime import datetime, timezone
from typing import Optional, Any

from painkiller.core.domain.models import (
    ClarificationRequest,
    ClarificationStatus,
    DeploymentInfo,
    DeploymentStatus,
    Project,
    Task,
    TaskStatus,
)
from painkiller.core.ports.deployment import DeploymentPort
from painkiller.core.ports.git import GitPort
from painkiller.core.ports.issue_tracker import IssueTrackerPort
from painkiller.core.ports.sandbox import SandboxPort
from painkiller.engine.verification import detect_test_command, judge

logger = logging.getLogger(__name__)


class PainkillerOrchestrator:
    """Coordinates task execution, git branches, docker containers, and status transitions."""

    def __init__(
        self,
        tracker: IssueTrackerPort,
        sandbox: SandboxPort,
        git: GitPort,
        vcs: Optional[Any] = None,
        deployer: Optional[DeploymentPort] = None,
    ):
        self.tracker = tracker
        self.sandbox = sandbox
        self.git = git
        self.vcs = vcs
        self.deployer = deployer

    # ---- execução de tarefas ----------------------------------------------

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

        # Build prompt instructions. As respostas já dadas pelo analista entram
        # aqui: sem isso o agente refaria a mesma pergunta a cada reexecução.
        history = await self._clarification_history(task.id)
        instructions = self._build_task_instructions(task, project, history)

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
                comment=f"Pausada para esclarecimento: {result.clarification.question}",
            )
        elif result.exit_code == 0:
            passed, note = await self._verify(project)
            if passed:
                await self.git.commit_wip(project.repo_path, f"feat: implement {task.title}")
                try:
                    await self.git.push(project.repo_path, branch_name)
                except Exception as push_err:
                    logger.debug(f"Git push skipped or failed: {push_err}")

                await self.tracker.update_task_status(task.id, TaskStatus.IN_REVIEW)
                await self.tracker.add_comment(
                    task.id,
                    author="system",
                    comment=f"Tarefa concluída pelo agente. {note} Pronta para revisão.",
                )
            else:
                await self.tracker.update_task_status(task.id, TaskStatus.FAILED)
                await self.tracker.add_comment(
                    task.id,
                    author="system",
                    comment=f"Verificação falhou após a execução do agente:\n{note}",
                )
        else:
            await self.tracker.update_task_status(task.id, TaskStatus.FAILED)
            await self.tracker.add_comment(
                task.id,
                author="system",
                comment=f"Agente terminou com código {result.exit_code}:\n{result.logs}",
            )

        updated_task = await self.tracker.get_task(task.id)
        return updated_task or task

    async def _verify(self, project: Project) -> tuple[bool, str]:
        """Run the project's verification command, or skip when there is nothing to run."""
        command = (project.test_command or "").strip() or detect_test_command(project.repo_path)
        if not command:
            return True, "Nenhum comando de verificação configurado ou detectado; etapa de testes pulada."
        code, output = await self.git.run_tests(project.repo_path, command)
        verdict = judge(command, code, output)
        return verdict.passed, verdict.note

    async def _clarification_history(self, task_id: str) -> list[ClarificationRequest]:
        try:
            items = await self.tracker.list_clarifications(task_id)
        except Exception as e:  # tracker antigo sem o método, ou falha de I/O
            logger.debug(f"Could not load clarification history for {task_id}: {e}")
            return []
        if not isinstance(items, list):
            return []
        return [c for c in items if isinstance(c, ClarificationRequest)]

    async def reply_clarification(self, clarification_id: str, answer: str) -> Task:
        """Provide answer to a paused clarification and resume the task."""
        clar = await self.tracker.resolve_clarification(clarification_id, answer)
        await self.tracker.add_comment(
            clar.task_id,
            author="analyst",
            comment=f"Analista respondeu: {answer}",
        )
        return await self.dispatch_task(clar.task_id)

    def _build_task_instructions(
        self,
        task: Task,
        project: Project,
        clarifications: Optional[list[ClarificationRequest]] = None,
    ) -> str:
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

        answered = [
            c for c in (clarifications or [])
            if c.status == ClarificationStatus.ANSWERED and c.answer
        ]
        if answered:
            instructions.append(
                "\n## Esclarecimentos já respondidos pelo analista:\n"
                "Estas dúvidas já foram resolvidas. NÃO pergunte de novo; siga as respostas."
            )
            for c in answered:
                where = f" (contexto: {c.context_summary})" if c.context_summary else ""
                instructions.append(f"- Pergunta: {c.question}{where}\n  Resposta: {c.answer}")

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
            comment=f"Tarefa aprovada e incorporada na branch principal ({project.default_branch}).",
        )

        # Uma aplicação já publicada acompanha a branch principal: cada merge
        # aprovado vira um novo deploy. Falha aqui não desfaz o merge.
        if project.deployment and project.deployment.app_uuid and self.deployer:
            try:
                await self.publish_project(project.id)
            except Exception as e:
                logger.warning(f"Redeploy after merge failed for {project.id}: {e}")

        updated_task = await self.tracker.get_task(task.id)
        return updated_task or task

    # ---- publicação ---------------------------------------------------------

    def can_publish(self) -> bool:
        return bool(self.deployer and self.deployer.is_configured())

    async def publish_project(self, project_id: str) -> Project:
        """Create the hosting application if needed and trigger a deploy of the default branch."""
        if not self.deployer:
            raise RuntimeError("Nenhum provedor de publicação configurado nesta instalação.")
        project = await self.tracker.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        # Garante que a branch principal esteja no remoto antes de o provedor clonar.
        try:
            await self.git.push(project.repo_path, project.default_branch)
        except Exception as e:
            logger.debug(f"Push before publish skipped or failed: {e}")

        info = project.deployment or DeploymentInfo()
        try:
            info = await self.deployer.ensure_application(project)
            project = await self.tracker.update_project(project_id, deployment=info)
            info = await self.deployer.deploy(project)
        except Exception as e:
            failed = info.model_copy(
                update={
                    "status": DeploymentStatus.FAILED,
                    "error": str(e),
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            await self.tracker.update_project(project_id, deployment=failed)
            raise

        return await self.tracker.update_project(project_id, deployment=info)

    async def refresh_deployment(self, project_id: str) -> Project:
        """Poll the provider and persist the current deployment status."""
        project = await self.tracker.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        if not (self.deployer and project.deployment and project.deployment.app_uuid):
            return project
        try:
            info = await self.deployer.refresh_status(project)
        except Exception as e:
            logger.debug(f"Deployment status refresh failed for {project_id}: {e}")
            return project
        return await self.tracker.update_project(project_id, deployment=info)
