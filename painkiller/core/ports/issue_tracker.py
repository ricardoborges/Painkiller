"""Issue Tracker Port contract."""

from abc import ABC, abstractmethod
from typing import Optional, Sequence
from painkiller.core.domain.models import Project, Task, TaskStatus, ClarificationRequest


class IssueTrackerPort(ABC):
    """Abstract port for issue tracking backends (SQLite, Redmine, GitLab, GitHub)."""

    @abstractmethod
    async def create_project(
        self,
        name: str,
        repo_path: str,
        description: str = "",
        purpose: str = "",
        solution_description: str = "",
        attachments: Optional[Sequence[str]] = None,
        default_branch: str = "main",
    ) -> Project:
        """Create or register a project."""
        pass

    @abstractmethod
    async def list_projects(self) -> list[Project]:
        """List all registered projects."""
        pass

    @abstractmethod
    async def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        purpose: Optional[str] = None,
        solution_description: Optional[str] = None,
        attachments: Optional[Sequence[str]] = None,
    ) -> Project:
        """Update an existing project."""
        pass

    @abstractmethod
    async def delete_project(self, project_id: str) -> None:
        """Delete a project and its associated tasks."""
        pass

    @abstractmethod
    async def get_project(self, project_id: str) -> Optional[Project]:
        """Retrieve a project by ID."""
        pass

    @abstractmethod
    async def create_task(
        self,
        project_id: str,
        title: str,
        description: str,
        target_files: Optional[Sequence[str]] = None,
        acceptance_criteria: Optional[Sequence[str]] = None,
        dependencies: Optional[Sequence[str]] = None,
    ) -> Task:
        """Create a new task."""
        pass

    @abstractmethod
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve a task by ID."""
        pass

    @abstractmethod
    async def list_tasks(
        self,
        project_id: str,
        status: Optional[TaskStatus] = None,
    ) -> list[Task]:
        """List tasks for a project, optionally filtered by status."""
        pass

    @abstractmethod
    async def update_task_status(self, task_id: str, status: TaskStatus) -> Task:
        """Update the lifecycle status of a task."""
        pass

    @abstractmethod
    async def add_comment(self, task_id: str, author: str, comment: str) -> None:
        """Add an audit comment to a task issue."""
        pass

    @abstractmethod
    async def create_clarification(
        self,
        task_id: str,
        question: str,
        context_summary: str,
    ) -> ClarificationRequest:
        """Record an agent clarification request."""
        pass

    @abstractmethod
    async def resolve_clarification(
        self,
        clarification_id: str,
        answer: str,
    ) -> ClarificationRequest:
        """Resolve a clarification question with the analyst's answer."""
        pass

    @abstractmethod
    async def get_pending_clarification(self, task_id: str) -> Optional[ClarificationRequest]:
        """Get the current pending clarification request for a task, if any."""
        pass
