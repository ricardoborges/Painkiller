"""Git Port contract."""

from abc import ABC, abstractmethod
from typing import Optional


class GitPort(ABC):
    """Abstract port for repository and VCS operations."""

    @abstractmethod
    async def create_branch(self, repo_path: str, branch_name: str, base_branch: str = "main") -> None:
        """Create and checkout a new branch."""
        pass

    @abstractmethod
    async def commit_wip(self, repo_path: str, message: str) -> str:
        """Commit all current work-in-progress changes."""
        pass

    @abstractmethod
    async def get_diff(self, repo_path: str, base_branch: str = "main") -> str:
        """Get the full git diff against the base branch."""
        pass

    @abstractmethod
    async def has_changes(self, repo_path: str) -> bool:
        """Check whether there are uncommitted or committed changes compared to base."""
        pass

    @abstractmethod
    async def run_tests(self, repo_path: str, test_command: Optional[str] = None) -> tuple[int, str]:
        """Execute project acceptance tests in the repository."""
        pass
