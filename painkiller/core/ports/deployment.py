"""Deployment Port contract for provisioning and managing environments."""

from abc import ABC, abstractmethod
from typing import Optional
from painkiller.core.domain.models import DeploymentComponent, DeploymentRecord, EnvironmentType, Project


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
        component: DeploymentComponent = DeploymentComponent.APP,
        env_vars: Optional[dict[str, str]] = None,
    ) -> DeploymentRecord:
        """Trigger an automatic deployment of a project environment.

        Provisions project and application if they don't exist yet in the target platform,
        configures the git branch and wildcard domain, and triggers the deployment.
        ``component`` picks the app's web build or its ``backend/``: each is its own
        application, with its own host. ``env_vars`` are set on the application
        before the build (the backend's secrets).
        """
        pass

    def environment_url(
        self,
        project: Project,
        environment: EnvironmentType,
        component: DeploymentComponent = DeploymentComponent.APP,
    ) -> Optional[str]:
        """Address an environment answers at, known before (and without) a deploy; None if unknown."""
        return None

    async def remove_env(
        self,
        project: Project,
        environment: EnvironmentType,
        component: DeploymentComponent,
        name: str,
    ) -> None:
        """Drop a variable from the application of that environment, if both exist."""

    @abstractmethod
    async def get_deployment_status(self, record: DeploymentRecord) -> DeploymentRecord:
        """Query the platform for the latest status and public URL of a deployment."""
        pass

    @abstractmethod
    async def get_deployment_logs(self, record: DeploymentRecord) -> str:
        """Fetch deployment and build logs from the platform."""
        pass
