"""Core domain entities and value objects for Painkiller."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Lifecycle statuses for an engineering task."""
    BACKLOG = "BACKLOG"
    READY = "READY"
    RUNNING = "RUNNING"
    AWAITING_ANALYST = "AWAITING_ANALYST"
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ClarificationStatus(str, Enum):
    """Status of an analyst clarification question."""
    PENDING = "PENDING"
    ANSWERED = "ANSWERED"


class ClarificationRequest(BaseModel):
    """A clarification request triggered when an agent encounters ambiguity."""
    id: str
    task_id: str
    question: str
    context_summary: str
    status: ClarificationStatus = ClarificationStatus.PENDING
    answer: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    answered_at: Optional[datetime] = None

    def resolve(self, answer: str) -> None:
        self.answer = answer
        self.status = ClarificationStatus.ANSWERED
        self.answered_at = datetime.now(timezone.utc)


class Task(BaseModel):
    """An atomic engineering task delegated to a coding agent."""
    id: str
    project_id: str
    title: str
    description: str
    target_files: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.BACKLOG
    assigned_branch: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def mark_ready(self) -> None:
        self.status = TaskStatus.READY
        self.updated_at = datetime.now(timezone.utc)

    def mark_running(self) -> None:
        self.status = TaskStatus.RUNNING
        self.updated_at = datetime.now(timezone.utc)

    def mark_awaiting_analyst(self) -> None:
        self.status = TaskStatus.AWAITING_ANALYST
        self.updated_at = datetime.now(timezone.utc)

    def mark_in_review(self) -> None:
        self.status = TaskStatus.IN_REVIEW
        self.updated_at = datetime.now(timezone.utc)

    def mark_completed(self) -> None:
        self.status = TaskStatus.COMPLETED
        self.updated_at = datetime.now(timezone.utc)

    def mark_failed(self) -> None:
        self.status = TaskStatus.FAILED
        self.updated_at = datetime.now(timezone.utc)


class Project(BaseModel):
    """Target software project managed by Painkiller."""
    id: str
    name: str
    repo_path: str
    default_branch: str = "main"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionResult(BaseModel):
    """Outcome of running a task in a sandbox container."""
    exit_code: int
    logs: str
    clarification: Optional[ClarificationRequest] = None
