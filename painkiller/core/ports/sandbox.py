"""Sandbox Port contract for isolated agent execution."""

from abc import ABC, abstractmethod
from painkiller.core.domain.models import Task, ExecutionResult


class SandboxPort(ABC):
    """Abstract port for executing tasks inside isolated containerized environments."""

    @abstractmethod
    async def run_task(
        self,
        task: Task,
        repo_path: str,
        task_instructions: str,
        timeout_seconds: int = 600,
    ) -> ExecutionResult:
        """Run an isolated worker on a task and return the execution result."""
        pass

    @abstractmethod
    async def stop_task(self, task_id: str) -> None:
        """Force-stop any running container for a task."""
        pass
