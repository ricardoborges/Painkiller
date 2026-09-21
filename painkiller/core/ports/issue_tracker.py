"""Issue Tracker Port contract."""

from abc import ABC, abstractmethod
from typing import Optional, Sequence
from painkiller.core.domain.models import (
    Project,
    Task,
    TaskStatus,
    ClarificationRequest,
    AnalysisSession,
    AgentEvent,
    IterationSession,
    SessionStatus,
)


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
        repo_url: Optional[str] = None,
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
        repo_url: Optional[str] = None,
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
        session_id: Optional[str] = None,
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
        session_id: Optional[str] = None,
    ) -> list[Task]:
        """List tasks for a project, optionally filtered by status or session."""
        pass

    @abstractmethod
    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        assigned_branch: Optional[str] = None,
        error: Optional[str] = None,
        last_comment: Optional[str] = None,
    ) -> Task:
        """Update the lifecycle status and execution metadata of a task."""
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

    @abstractmethod
    async def save_analysis_session(self, session: AnalysisSession) -> AnalysisSession:
        """Create or update an interactive analysis session."""
        pass

    @abstractmethod
    async def get_analysis_session(self, session_id: str) -> Optional[AnalysisSession]:
        """Retrieve an analysis session by ID."""
        pass

    @abstractmethod
    async def get_active_analysis_session(self, project_id: str) -> Optional[AnalysisSession]:
        """Get the current active (non-finished, non-failed) analysis session for a project."""
        pass

    @abstractmethod
    async def save_analysis_event(self, session_id: str, event: AgentEvent) -> None:
        """Record a canonical agent event for replay and auditing."""
        pass

    @abstractmethod
    async def list_analysis_events(self, session_id: str) -> list[AgentEvent]:
        """Retrieve chronological events recorded for a session."""
        pass

    @abstractmethod
    async def ensure_initial_session(self, project_id: str) -> IterationSession:
        """Ensure Session 1 exists for the project, creating it if needed."""
        pass

    @abstractmethod
    async def create_session(
        self,
        project_id: str,
        title: Optional[str] = None,
    ) -> IterationSession:
        """Create the next incremental agile iteration session for the project."""
        pass

    @abstractmethod
    async def list_sessions(self, project_id: str) -> list[IterationSession]:
        """List all iteration sessions for a project, ordered by number ascending."""
        pass

    @abstractmethod
    async def get_session(self, session_id: str) -> Optional[IterationSession]:
        """Retrieve an iteration session by ID."""
        pass

    @abstractmethod
    async def update_session(self, session: IterationSession) -> IterationSession:
        """Update an iteration session."""
        pass

    @abstractmethod
    async def migrate_tasks_to_session(
        self,
        task_ids: Sequence[str],
        target_session_id: str,
    ) -> list[Task]:
        """Move tasks to a target iteration session."""
        pass
