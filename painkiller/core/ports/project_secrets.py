"""Project Secrets Port contract."""

from abc import ABC, abstractmethod
from typing import Optional

from painkiller.core.domain.models import ProjectSecret, SecretScope


class ProjectSecretsPort(ABC):
    """Secrets of the app a project builds (API keys of the services it calls).

    Os valores ficam cifrados e só saem por ``get_secret_values``, para os
    builds e o deploy; nenhuma rota os devolve.
    """

    @abstractmethod
    async def list_secrets(self, project_id: str) -> list[ProjectSecret]:
        """Names and scopes of the project's secrets, sorted by name."""

    @abstractmethod
    async def get_secret_values(
        self, project_id: str, scope: Optional[SecretScope] = None
    ) -> dict[str, str]:
        """Name → plain value, optionally only of one scope. Unreadable values are left out."""

    @abstractmethod
    async def put_secret(self, project_id: str, name: str, scope: SecretScope, value: str) -> ProjectSecret:
        """Create or replace a secret."""

    @abstractmethod
    async def delete_secret(self, project_id: str, name: str) -> Optional[ProjectSecret]:
        """Remove a secret; returns what was removed, or None if it did not exist."""
