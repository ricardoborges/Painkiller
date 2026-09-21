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
    description: str = ""
    purpose: str = ""
    solution_description: str = ""
    attachments: list[str] = Field(default_factory=list)
    default_branch: str = "main"
    repo_url: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutionResult(BaseModel):
    """Outcome of running a task in a sandbox container."""
    exit_code: int
    logs: str
    clarification: Optional[ClarificationRequest] = None


class AgentEventType(str, Enum):
    """Kinds of event emitted by a live agent session."""
    SYSTEM = "SYSTEM"
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    THINKING = "THINKING"
    # Pedaços de texto conforme o modelo produz. Transitórios: não entram no
    # buffer de replay, porque o ASSISTANT canônico chega logo depois com o
    # texto inteiro. Ver AnalysisOrchestrator._pump.
    ASSISTANT_DELTA = "ASSISTANT_DELTA"
    THINKING_DELTA = "THINKING_DELTA"
    TOOL_USE = "TOOL_USE"
    TOOL_RESULT = "TOOL_RESULT"
    RESULT = "RESULT"
    ERROR = "ERROR"
    EXIT = "EXIT"


class AgentEvent(BaseModel):
    """A single event streamed out of a running agent session."""
    type: AgentEventType
    text: str = ""
    # Payload bruto do stream-json do Claude Code, preservado para o front
    # mostrar detalhes (nome da ferramenta, custo, modelo) sem que o backend
    # precise modelar cada variante.
    raw: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AnalysisStatus(str, Enum):
    """Lifecycle of an initial-analysis session."""
    STARTING = "STARTING"
    WAITING_AGENT = "WAITING_AGENT"
    WAITING_ANALYST = "WAITING_ANALYST"
    FINISHED = "FINISHED"
    FAILED = "FAILED"


class AnalysisSession(BaseModel):
    """A live brainstorming session between the analyst and a containerized agent."""
    id: str
    project_id: str
    status: AnalysisStatus = AnalysisStatus.STARTING
    container_name: Optional[str] = None
    claude_session_id: Optional[str] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None
    spec_path: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UsageSource(str, Enum):
    """Which part of Painkiller consumed the tokens."""
    ANALYSIS = "ANALYSIS"
    TASK = "TASK"
    LLM = "LLM"


class UsageRecord(BaseModel):
    """Tokens spent by one agent turn, one task run or one direct LLM call."""
    id: str = ""
    source: UsageSource
    model: str = ""
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    # Entrada inclui tokens de cache: superestima um pouco quando o provedor
    # cobra cache mais barato, mas nunca esconde gasto.
    input_tokens: int = 0
    output_tokens: int = 0
    # Custo que a própria ferramenta reportou (Claude Code, Aider). Vazio
    # quando só temos tokens e o preço sai da tabela.
    reported_cost_usd: Optional[float] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModelPrice(BaseModel):
    """USD per million tokens."""
    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0


class UsageSettings(BaseModel):
    """Analyst-defined pricing overrides, shared by every project.

    O orçamento não mora aqui: é por projeto (`UsageLedgerPort.get_project_budget`).
    """
    # Quantas unidades da moeda local valem 1 USD. Vazio = só mostra USD.
    exchange_rate: Optional[float] = None
    local_currency: str = "BRL"
    prices: dict[str, ModelPrice] = Field(default_factory=dict)
