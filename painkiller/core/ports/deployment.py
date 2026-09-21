"""Deployment Port contract for provisioning and managing environments."""

from abc import ABC, abstractmethod
from typing import Optional
from painkiller.core.domain.models import Project, DeploymentRecord, EnvironmentType


class DeploymentPort(ABC):
    """Abstract port for deployment orchestration backends (Coolify, etc.)."""

    @abstractmethod
    async def deploy_environment(
        self,
        project: Project,
        environment: EnvironmentType,
        branch: str,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> DeploymentRecord:
        """Trigger an automatic deployment of a project environment.
        
        Provisions project and application if they don't exist yet in the target platform,
        configures the git branch and wildcard domain, and triggers the deployment.
        """
        pass

    @abstractmethod
    async def get_deployment_status(self, record: DeploymentRecord) -> DeploymentRecord:
        """Query the platform for the latest status and public URL of a deployment."""
        pass

    @abstractmethod
    async def get_deployment_logs(self, record: DeploymentRecord) -> str:
        """Fetch deployment and build logs from the platform."""
        pass
