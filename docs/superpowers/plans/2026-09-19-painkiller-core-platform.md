# Painkiller Core Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the complete core foundation of Painkiller: domain entities, hexagonal ports, SQLite reference issue tracker, Git adapter, in-container CLI interruption protocol (`painkiller ask`), Docker sandbox worker runner, state machine orchestrator, interrogation engine, and FastAPI REST/WebSocket API.

**Architecture:** Monolithic Hexagonal Architecture (Ports & Adapters) separating pure domain models from infrastructure adapters (SQLite, Docker, Git, LiteLLM) and exposing orchestration via an asynchronous engine and FastAPI web interface.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 (asyncio + SQLite), Docker SDK (`docker-py`), LiteLLM, Pytest (`pytest-asyncio`).

**Spec:** [2026-09-19-painkiller-design.md](file:///d:/dev/github/Painkiller/docs/superpowers/specs/2026-09-19-painkiller-design.md)

## Global Constraints

- OS: Windows 11 host with PowerShell commands.
- Python: Version 3.11 or higher.
- Strict Hexagonal Architecture: `core/domain` and `core/ports` must have ZERO dependencies on external frameworks (no FastAPI, no SQLAlchemy, no Docker imports in core).
- All asynchronous I/O must use `async`/`await`.
- Every task includes unit or integration tests following TDD.

---

### Task 1: Project Scaffolding & Dependencies Setup

**Files:**
- Create: `pyproject.toml`
- Create: `painkiller/__init__.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Consumes: None
- Produces: Project package structure and testing harness

- [ ] **Step 1: Write `pyproject.toml` configuration**

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "painkiller"
version = "0.1.0"
description = "Automated software development platform via agent orchestration"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.8.0",
    "sqlalchemy[asyncio]>=2.0.30",
    "aiosqlite>=0.20.0",
    "docker>=7.1.0",
    "litellm>=1.40.0",
    "click>=8.1.0",
    "websockets>=12.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
]

[project.scripts]
painkiller = "painkiller.cli.main:cli"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 2: Create root package and test harness**

Create empty `painkiller/__init__.py` and `tests/conftest.py`.

- [ ] **Step 3: Run pytest to verify environment test discovery**

Run: `pytest`
Expected: 0 tests collected, 0 errors.

- [ ] **Step 4: Commit**

```powershell
git add pyproject.toml painkiller/__init__.py tests/conftest.py; git commit -m "chore: scaffold project structure and dependencies"
```

---

### Task 2: Core Domain Entities & Value Objects

**Files:**
- Create: `painkiller/core/domain/models.py`
- Test: `tests/unit/test_domain_models.py`

**Interfaces:**
- Consumes: None
- Produces: `TaskStatus`, `ClarificationStatus`, `Project`, `Task`, `ClarificationRequest`, `ExecutionResult`

- [ ] **Step 1: Write the failing unit test for domain models**

```python
# tests/unit/test_domain_models.py
from datetime import datetime
from painkiller.core.domain.models import (
    TaskStatus,
    ClarificationStatus,
    Project,
    Task,
    ClarificationRequest,
    ExecutionResult,
)

def test_task_lifecycle_status_transitions():
    task = Task(
        id="task-1",
        project_id="proj-1",
        title="Criar endpoint de login",
        description="Implementar autenticação JWT",
        target_files=["auth.py"],
        acceptance_criteria=["Deve retornar 200 e token"],
    )
    assert task.status == TaskStatus.BACKLOG
    task.mark_ready()
    assert task.status == TaskStatus.READY
    task.mark_running()
    assert task.status == TaskStatus.RUNNING
    task.mark_awaiting_analyst()
    assert task.status == TaskStatus.AWAITING_ANALYST
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_domain_models.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'painkiller.core.domain'`

- [ ] **Step 3: Implement domain models in `painkiller/core/domain/models.py`**

```python
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

class TaskStatus(str, Enum):
    BACKLOG = "BACKLOG"
    READY = "READY"
    RUNNING = "RUNNING"
    AWAITING_ANALYST = "AWAITING_ANALYST"
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class ClarificationStatus(str, Enum):
    PENDING = "PENDING"
    ANSWERED = "ANSWERED"

class ClarificationRequest(BaseModel):
    id: str
    task_id: str
    question: str
    context_summary: str
    status: ClarificationStatus = ClarificationStatus.PENDING
    answer: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    answered_at: Optional[datetime] = None

class Task(BaseModel):
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
    id: str
    name: str
    repo_path: str
    default_branch: str = "main"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ExecutionResult(BaseModel):
    exit_code: int
    logs: str
    clarification: Optional[ClarificationRequest] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_domain_models.py`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add painkiller/core/domain/models.py tests/unit/test_domain_models.py; git commit -m "feat(domain): implement core domain models and status transitions"
```

---

### Task 3: Core Domain Ports (Abstract Interfaces)

**Files:**
- Create: `painkiller/core/ports/issue_tracker.py`
- Create: `painkiller/core/ports/sandbox.py`
- Create: `painkiller/core/ports/git.py`
- Create: `painkiller/core/ports/llm.py`
- Test: `tests/unit/test_ports.py`

**Interfaces:**
- Consumes: `Task`, `Project`, `ClarificationRequest`, `ExecutionResult`, `TaskStatus`
- Produces: Abstract base classes: `IssueTrackerPort`, `SandboxPort`, `GitPort`, `LLMPort`

- [ ] **Step 1: Write test to verify port contracts cannot be instantiated directly**

```python
# tests/unit/test_ports.py
import pytest
from painkiller.core.ports.issue_tracker import IssueTrackerPort
from painkiller.core.ports.sandbox import SandboxPort
from painkiller.core.ports.git import GitPort
from painkiller.core.ports.llm import LLMPort

def test_ports_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        IssueTrackerPort()
    with pytest.raises(TypeError):
        SandboxPort()
    with pytest.raises(TypeError):
        GitPort()
    with pytest.raises(TypeError):
        LLMPort()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_ports.py`
Expected: FAIL

- [ ] **Step 3: Define abstract port interfaces**

Implement `IssueTrackerPort`, `SandboxPort`, `GitPort`, and `LLMPort` using `abc.ABC` and `@abstractmethod`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_ports.py`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add painkiller/core/ports/ tests/unit/test_ports.py; git commit -m "feat(ports): define abstract hexagonal contracts"
```

---

### Task 4: SQLite Reference Issue Tracker Adapter

**Files:**
- Create: `painkiller/adapters/issue_trackers/sqlite_tracker.py`
- Test: `tests/integration/test_sqlite_tracker.py`

**Interfaces:**
- Consumes: `IssueTrackerPort`, `Task`, `Project`, `ClarificationRequest`
- Produces: `SQLiteIssueTracker` (async SQLAlchemy SQLite implementation)

- [ ] **Step 1: Write failing integration test for SQLite Issue Tracker**

Test project creation, task creation, status updates, adding clarification questions, and answering them.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_sqlite_tracker.py`
Expected: FAIL

- [ ] **Step 3: Implement `SQLiteIssueTracker`**

Use SQLAlchemy AsyncSession with SQLite (`sqlite+aiosqlite:///:memory:` or local file), mapping relational tables to domain `Task` and `ClarificationRequest`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_sqlite_tracker.py`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add painkiller/adapters/issue_trackers/ tests/integration/test_sqlite_tracker.py; git commit -m "feat(adapters): implement SQLite issue tracker reference adapter"
```

---

### Task 5: In-Container CLI Protocol (`painkiller ask`)

**Files:**
- Create: `painkiller/cli/ask.py`
- Create: `painkiller/cli/main.py`
- Test: `tests/unit/test_cli_ask.py`

**Interfaces:**
- Consumes: `ClarificationRequest` format
- Produces: CLI tool with subcommands (specifically `painkiller ask "<question>" --context "<context>"`)

- [ ] **Step 1: Write failing unit test for `painkiller ask` command**

Verify that running the ask command creates `/.painkiller/clarification.json` and exits with code 42.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_cli_ask.py`
Expected: FAIL

- [ ] **Step 3: Implement CLI ask command using Click or Typer**

Writes structured JSON with question, context, timestamp and issues `sys.exit(42)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_cli_ask.py`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add painkiller/cli/ tests/unit/test_cli_ask.py; git commit -m "feat(cli): implement in-container painkiller ask interruption protocol"
```

---

### Task 6: Git CLI Adapter

**Files:**
- Create: `painkiller/adapters/git/git_adapter.py`
- Test: `tests/integration/test_git_adapter.py`

**Interfaces:**
- Consumes: `GitPort`
- Produces: `GitCliAdapter` executing git commands asynchronously

- [ ] **Step 1: Write failing integration test on a temporary local git repository**

Test branch creation, checking status, committing WIP, diff generation.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_git_adapter.py`
Expected: FAIL

- [ ] **Step 3: Implement `GitCliAdapter`**

Uses `asyncio.create_subprocess_exec("git", ...)` to execute git operations safely with branch checks and diff capture.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_git_adapter.py`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add painkiller/adapters/git/ tests/integration/test_git_adapter.py; git commit -m "feat(git): implement Git CLI adapter"
```

---

### Task 7: Docker Sandbox Worker Runner & Dockerfile

**Files:**
- Create: `docker/worker.Dockerfile`
- Create: `painkiller/adapters/sandbox/docker_runner.py`
- Test: `tests/integration/test_docker_runner.py`

**Interfaces:**
- Consumes: `SandboxPort`, `Task`, `ExecutionResult`
- Produces: `DockerSandboxRunner` using `docker-py` with timeout and exit code 42 handling

- [ ] **Step 1: Write `docker/worker.Dockerfile`**

Includes python, node, git, aider-chat, and installs painkiller package so `painkiller ask` is available on PATH.

- [ ] **Step 2: Write test for `DockerSandboxRunner` exit code parsing and clarification detection**

Mock docker container run to return exit code 42 with mock clarification JSON.

- [ ] **Step 3: Implement `DockerSandboxRunner`**

Launches ephemeral container with volume mounted, stream logs, catch exit code 42, read `clarification.json`, return `ExecutionResult`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_docker_runner.py`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add docker/ painkiller/adapters/sandbox/ tests/integration/test_docker_runner.py; git commit -m "feat(sandbox): implement Docker sandbox runner and worker image"
```

---

### Task 8: Orchestrator Engine & State Machine

**Files:**
- Create: `painkiller/engine/orchestrator.py`
- Test: `tests/unit/test_orchestrator.py`

**Interfaces:**
- Consumes: `IssueTrackerPort`, `SandboxPort`, `GitPort`
- Produces: `PainkillerOrchestrator` managing the full task execution lifecycle

- [ ] **Step 1: Write failing unit test for orchestrator lifecycle with mocks**

Simulate:
1. Dispatch task -> creates branch -> runs sandbox.
2. Sandbox returns code 42 (clarification) -> updates issue to `AWAITING_ANALYST`.
3. Analyst answers clarification -> task returns to `RUNNING` -> completes -> PR created -> `IN_REVIEW`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_orchestrator.py`
Expected: FAIL

- [ ] **Step 3: Implement `PainkillerOrchestrator`**

Coordinates task dispatch, branch switching, container execution, clarification resolution and state transitions.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_orchestrator.py`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add painkiller/engine/ tests/unit/test_orchestrator.py; git commit -m "feat(engine): implement task orchestrator and state machine"
```

---

### Task 9: Interrogation Wizard & Structured Backlog Generator

**Files:**
- Create: `painkiller/adapters/llm/litellm_adapter.py`
- Create: `painkiller/interrogation/wizard.py`
- Test: `tests/unit/test_interrogation_wizard.py`

**Interfaces:**
- Consumes: `LLMPort`, `IssueTrackerPort`
- Produces: `InterrogationWizard` conducting single-question interviews and decomposing into atomic tasks

- [ ] **Step 1: Write failing test with mock LLM for interview steps and backlog parsing**

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_interrogation_wizard.py`
Expected: FAIL

- [ ] **Step 3: Implement `LiteLLMAdapter` and `InterrogationWizard`**

Supports iterative Q&A, compiles architecture spec, and parses JSON output into `list[Task]` directly in the issue tracker.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_interrogation_wizard.py`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add painkiller/adapters/llm/ painkiller/interrogation/ tests/unit/test_interrogation_wizard.py; git commit -m "feat(interrogation): implement interrogation wizard and backlog generator"
```

---

### Task 10: FastAPI Application, REST Endpoints, WebSockets & Web Dashboard

**Files:**
- Create: `painkiller/api/server.py`
- Create: `painkiller/api/routes/projects.py`
- Create: `painkiller/api/routes/tasks.py`
- Create: `painkiller/api/routes/interrogation.py`
- Create: `painkiller/api/static/index.html`
- Test: `tests/integration/test_api.py`

**Interfaces:**
- Consumes: `PainkillerOrchestrator`, `SQLiteIssueTracker`, `InterrogationWizard`
- Produces: Runnable web server with live Kanban and Interrogation UI

- [ ] **Step 1: Write integration tests using FastAPI TestClient**

Test:
- `POST /api/projects`
- `GET /api/tasks`
- `POST /api/tasks/{id}/dispatch`
- `POST /api/tasks/{id}/clarification-reply`

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_api.py`
Expected: FAIL

- [ ] **Step 3: Implement FastAPI routes, WebSockets and minimalist responsive HTML/CSS dashboard**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_api.py`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add painkiller/api/ tests/integration/test_api.py; git commit -m "feat(api): implement REST endpoints, WebSockets and web dashboard"
```
