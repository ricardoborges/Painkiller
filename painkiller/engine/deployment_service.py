"""Deployment Service coordinating environment provisioning with Coolify."""

import logging
from typing import Optional, Any
from painkiller.core.domain.models import (
    Project,
    Task,
    TaskStatus,
    DeploymentRecord,
    DeploymentStatus,
    EnvironmentType,
)
from painkiller.core.ports.deployment import DeploymentPort
from painkiller.core.ports.issue_tracker import IssueTrackerPort

logger = logging.getLogger(__name__)


class DeploymentService:
    """Orchestrates testing and production deployment requests."""

    def __init__(self, tracker: IssueTrackerPort, deployment: DeploymentPort):
        self.tracker = tracker
        self.deployment = deployment

    async def trigger_deploy(
        self,
        project_id: str,
        environment: EnvironmentType,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> DeploymentRecord:
        """Trigger deployment of test or production environment."""
        project = await self.tracker.get_project(project_id)
        if not project:
            raise ValueError(f"Projeto {project_id} não encontrado")

        # Resolução da branch:
        # Para TESTE:
        # A branch da tarefa indicada ou, sem ela, a da última tarefa concluída.
        # Só a conclusão faz push da feature/ para o Gitea: uma tarefa em
        # execução (ou órfã após um restart) tem a branch só no disco, e o
        # Coolify falha com "Remote branch ... not found". Por isso uma tarefa
        # indicada que não esteja concluída cai na escolha automática. Sem
        # tarefa concluída, a branch padrão.
        # Para PRODUÇÃO:
        # Sempre usa a default_branch (main).
        branch = project.default_branch or "main"
        if environment == EnvironmentType.TEST:
            task = await self.tracker.get_task(task_id) if task_id else None
            if task and task.status == TaskStatus.COMPLETED:
                branch = task.assigned_branch or f"feature/{task.id}"
            else:
                task_id = None
                tasks = await self.tracker.list_tasks(project_id, session_id=session_id)
                completed = [t for t in tasks if t.status == TaskStatus.COMPLETED]
                if completed:
                    chosen_task = completed[-1]
                    branch = chosen_task.assigned_branch or f"feature/{chosen_task.id}"
                    task_id = chosen_task.id

        record = await self.deployment.deploy_environment(
            project=project,
            environment=environment,
            branch=branch,
            task_id=task_id,
            session_id=session_id,
        )

        # Salva o registro inicial no banco
        saved = await self.tracker.save_deployment(record)

        # Atualiza a URL do projeto
        if saved.url:
            if environment == EnvironmentType.TEST:
                await self.tracker.update_project_deployment_urls(project_id, test_url=saved.url)
            elif environment == EnvironmentType.PRODUCTION:
                await self.tracker.update_project_deployment_urls(project_id, production_url=saved.url)

        return saved

    async def get_deployment(self, deployment_id: str) -> Optional[DeploymentRecord]:
        """Fetch deployment record and refresh status from Coolify if still pending/building."""
        record = await self.tracker.get_deployment(deployment_id)
        if not record:
            return None

        if record.status in (DeploymentStatus.PENDING, DeploymentStatus.BUILDING):
            updated = await self.deployment.get_deployment_status(record)
            if updated.status != record.status or updated.logs != record.logs:
                record = await self.tracker.save_deployment(updated)

        return record

    async def list_project_deployments(self, project_id: str, limit: int = 20) -> list[DeploymentRecord]:
        return await self.tracker.list_project_deployments(project_id, limit=limit)

    async def get_project_environment_status(self, project_id: str) -> dict[str, Any]:
        """Return status and URLs for both test and production environments."""
        project = await self.tracker.get_project(project_id)
        if not project:
            raise ValueError(f"Projeto {project_id} não encontrado")

        latest_test = await self.tracker.get_latest_deployment(project_id, EnvironmentType.TEST)
        latest_prod = await self.tracker.get_latest_deployment(project_id, EnvironmentType.PRODUCTION)

        # Atualiza status se estava em building
        if latest_test and latest_test.status in (DeploymentStatus.PENDING, DeploymentStatus.BUILDING):
            latest_test = await self.deployment.get_deployment_status(latest_test)
            await self.tracker.save_deployment(latest_test)

        if latest_prod and latest_prod.status in (DeploymentStatus.PENDING, DeploymentStatus.BUILDING):
            latest_prod = await self.deployment.get_deployment_status(latest_prod)
            await self.tracker.save_deployment(latest_prod)

        return {
            "project_id": project_id,
            "test": {
                "url": (latest_test.url if latest_test else None) or project.test_url,
                "status": latest_test.status if latest_test else None,
                "branch": latest_test.branch if latest_test else None,
                "updated_at": latest_test.updated_at if latest_test else None,
                "deployment_id": latest_test.id if latest_test else None,
            },
            "production": {
                "url": (latest_prod.url if latest_prod else None) or project.production_url,
                "status": latest_prod.status if latest_prod else None,
                "branch": latest_prod.branch if latest_prod else None,
                "updated_at": latest_prod.updated_at if latest_prod else None,
                "deployment_id": latest_prod.id if latest_prod else None,
            },
        }
