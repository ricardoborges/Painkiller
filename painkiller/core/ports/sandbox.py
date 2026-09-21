"""Sandbox Port contract for isolated agent execution."""

from abc import ABC, abstractmethod
from typing import Callable, Optional
from painkiller.core.domain.models import AgentEvent, Task, ExecutionResult

# Chamado a cada evento do agente enquanto o contêiner roda. Pode ser invocado
# de uma thread fora do event loop: quem recebe é responsável por reagendar.
AgentEventCallback = Callable[[AgentEvent], None]


class SandboxPort(ABC):
    """Abstract port for executing tasks inside isolated containerized environments."""

    @abstractmethod
    async def run_task(
        self,
        task: Task,
        repo_path: str,
        task_instructions: str,
        timeout_seconds: int = 600,
        on_event: Optional[AgentEventCallback] = None,
    ) -> ExecutionResult:
        """Run an isolated worker on a task and return the execution result.

        When ``on_event`` is given, each parsed line of the agent's output is
        handed to it as it is produced, so callers can show live progress.
        """
        pass

    @abstractmethod
    async def stop_task(self, task_id: str) -> None:
        """Force-stop any running container for a task."""
        pass
