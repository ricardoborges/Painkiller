"""Platform Settings Port contract."""

from abc import ABC, abstractmethod

from painkiller.core.domain.models import PlatformSettings


class PlatformSettingsPort(ABC):
    """Abstract port for the admin-edited platform configuration."""

    @abstractmethod
    async def get_platform_settings(self) -> PlatformSettings:
        """Return the stored settings (defaults when never saved)."""
        pass

    @abstractmethod
    async def save_platform_settings(self, settings: PlatformSettings) -> PlatformSettings:
        """Persist the settings, replacing what was stored."""
        pass

    @abstractmethod
    async def get_secret_key(self) -> str:
        """The installation's random key (signs sessions, seals secrets), created on first use."""
        pass
