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

    @abstractmethod
    async def init_repo(self, repo_path: str, default_branch: str = "main", initial_commit: bool = True) -> None:
        """Initialize a git repository if not already initialized, with initial commit."""
        pass

    @abstractmethod
    async def set_remote(self, repo_path: str, remote_url: str, remote_name: str = "origin") -> None:
        """Configure or update a git remote URL."""
        pass

    @abstractmethod
    async def push(self, repo_path: str, branch_name: str, remote_name: str = "origin", set_upstream: bool = True) -> tuple[int, str]:
        """Push branch to remote."""
        pass

    @abstractmethod
    async def merge_branch(self, repo_path: str, source_branch: str, target_branch: str = "main") -> tuple[int, str]:
        """Checkout target branch and merge source branch into it."""
        pass
