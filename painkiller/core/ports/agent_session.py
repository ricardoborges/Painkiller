"""Agent Session Port: a long-lived, interactive agent run.

Unlike SandboxPort, which fires a one-shot worker and returns a single result,
this port models a conversation: the session stays alive, streams events out and
accepts analyst answers in, until the agent decides it is done.
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional, Any

from painkiller.core.domain.models import AgentEvent


class AgentSessionPort(ABC):
    """Abstract port for an interactive agent session running in isolation."""

    @abstractmethod
    async def start(
        self,
        session_id: str,
        repo_path: str,
        prompt: str = "",
        env: Optional[dict[str, str]] = None,
        timeout_seconds: int = 3600,
        resume: bool = False,
        claude_session_id: Optional[str] = None,
        harness: Optional[Any] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        """Start or resume the session and return the container (or process) name."""

    @abstractmethod
    async def send(self, session_id: str, text: str) -> None:
        """Deliver an analyst answer to the running agent."""

    @abstractmethod
    def stream(self, session_id: str) -> AsyncIterator[AgentEvent]:
        """Yield events until the agent exits."""

    @abstractmethod
    async def close_input(self, session_id: str) -> None:
        """Signal end-of-input so the agent finishes its current turn and exits."""

    @abstractmethod
    async def stop(self, session_id: str) -> None:
        """Force-stop and remove the session's container."""

    @abstractmethod
    async def is_alive(self, session_id: str) -> bool:
        """Check if the session container or process is currently alive and running."""
