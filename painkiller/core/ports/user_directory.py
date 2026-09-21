"""User Directory Port contract."""

from abc import ABC, abstractmethod
from typing import Optional

from painkiller.core.domain.models import User


class UserDirectoryPort(ABC):
    """Abstract port for storing the people who sign in to Painkiller."""

    @abstractmethod
    async def create_user(
        self,
        email: str,
        name: str = "",
        google_sub: Optional[str] = None,
        gitea_username: Optional[str] = None,
    ) -> User:
        """Register a new (non-admin) user."""
        pass

    @abstractmethod
    async def get_user(self, user_id: str) -> Optional[User]:
        """Fetch a user by id."""
        pass

    @abstractmethod
    async def get_user_by_google_sub(self, google_sub: str) -> Optional[User]:
        """Fetch the user bound to a Google account."""
        pass

    @abstractmethod
    async def update_user(
        self,
        user_id: str,
        email: Optional[str] = None,
        name: Optional[str] = None,
        gitea_username: Optional[str] = None,
    ) -> User:
        """Update profile fields and the Gitea binding."""
        pass
