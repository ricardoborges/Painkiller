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
        password_hash: Optional[str] = None,
        is_active: bool = True,
        email_verified: bool = True,
        verification_code: Optional[str] = None,
        verification_token: Optional[str] = None,
        verification_expires_at: Optional[object] = None,
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
    async def get_user_by_email_or_username(self, identifier: str) -> Optional[User]:
        """Fetch a user by their email or gitea_username."""
        pass

    @abstractmethod
    async def get_user_by_verification_token(self, token: str) -> Optional[User]:
        """Fetch an unverified user by their verification token."""
        pass

    @abstractmethod
    async def activate_user(self, user_id: str) -> User:
        """Mark a user as active and email_verified, clearing verification tokens."""
        pass

    @abstractmethod
    async def update_user(
        self,
        user_id: str,
        email: Optional[str] = None,
        name: Optional[str] = None,
        gitea_username: Optional[str] = None,
        password_hash: Optional[str] = None,
        verification_code: Optional[str] = None,
        verification_token: Optional[str] = None,
        verification_expires_at: Optional[object] = None,
    ) -> User:
        """Update profile fields and the Gitea binding."""
        pass
