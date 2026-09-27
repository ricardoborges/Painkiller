"""Deployment Port: publishes a project's default branch to production.

O provedor concreto (Coolify, por exemplo) clona o repositório remoto do
projeto, constrói a imagem e expõe a aplicação numa URL. O core só conhece
este contrato e o `DeploymentInfo` que ele devolve.
"""

from abc import ABC, abstractmethod

from painkiller.core.domain.models import DeploymentInfo, Project


class DeploymentPort(ABC):
    """Abstract port for a hosting provider that builds and serves the project."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether the provider has credentials and targets to work with."""

    @abstractmethod
    async def ensure_application(self, project: Project) -> DeploymentInfo:
        """Create the provider-side application for the project if it does not exist yet.

        O código é buscado a partir de `project.repo_url` (o repositório remoto
        no Gitea). Idempotente: quando `project.deployment.app_uuid` já existe,
        devolve a informação atual sem criar nada.
        """

    @abstractmethod
    async def deploy(self, project: Project) -> DeploymentInfo:
        """Trigger a new build+deploy of the project's default branch."""

    @abstractmethod
    async def refresh_status(self, project: Project) -> DeploymentInfo:
        """Ask the provider for the latest deployment/application status."""
