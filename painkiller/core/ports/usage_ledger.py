"""Usage Ledger Port contract."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from painkiller.core.domain.models import ModelPrice, UsageRecord, UsageSettings


class UsageLedgerPort(ABC):
    """Abstract port for recording token consumption, prices and per-project budgets."""

    @abstractmethod
    async def record_usage(self, record: UsageRecord) -> UsageRecord:
        """Append one usage entry to the ledger."""
        pass

    @abstractmethod
    async def list_usage(
        self,
        project_id: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> list[UsageRecord]:
        """List usage entries, oldest first."""
        pass

    @abstractmethod
    async def get_usage_settings(self) -> UsageSettings:
        """Return the shared pricing settings (defaults when never saved)."""
        pass

    @abstractmethod
    async def save_usage_settings(self, settings: UsageSettings) -> UsageSettings:
        """Persist the shared pricing settings."""
        pass

    @abstractmethod
    async def get_project_budget(self, project_id: str) -> Optional[float]:
        """Return the project's budget in USD, or None when never defined."""
        pass

    @abstractmethod
    async def save_project_budget(self, project_id: str, budget_usd: Optional[float]) -> None:
        """Persist the project's budget in USD; None removes it."""
        pass

    @abstractmethod
    async def get_project_prices(self, project_id: str) -> dict[str, ModelPrice]:
        """Return the model prices this project overrides (empty when it inherits all)."""
        pass

    @abstractmethod
    async def save_project_prices(self, project_id: str, prices: dict[str, ModelPrice]) -> None:
        """Persist the project's price overrides; an empty dict removes them."""
        pass
