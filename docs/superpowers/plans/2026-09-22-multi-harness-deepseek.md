# Multi-Harness Support (Antigravity & DeepSeek) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to choose the agent harness (`agy + superpowers` vs `deepseek harness + superpowers`) and optionally provide an API Key when creating or editing a project, with fallback to global `.env`.

**Architecture:** Extend `Project` domain entity and SQLite schema with `harness` and `api_key` fields. Dynamically resolve Docker container images (`painkiller-agent:latest` vs `painkiller-agent-deepseek:latest` and `painkiller-worker:latest` vs `painkiller-worker-deepseek:latest`), credentials (`GEMINI_API_KEY` vs `DEEPSEEK_API_KEY`), and execution commands in `DockerAgentSession` and `DockerSandboxRunner`. Add UI selection controls and masked API key inputs in SvelteKit `ProjectDialog.svelte`.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, SQLAlchemy/SQLite, Docker, Node.js 22, SvelteKit 2, TypeScript.

**Spec:** `docs/superpowers/specs/2026-09-22-multi-harness-deepseek-design.md`

## Global Constraints

- Code comments, LLM prompts, API error messages and UI are in Portuguese (pt-BR); code identifiers and docstrings are in English.
- No Tailwind, no component libraries in frontend (Svelte 5 runes + scoped CSS + `web/src/app.css` tokens).
- Maintain clean interruption protocol (exit code 42 via `painkiller ask`) across all worker containers.
- Backward compatibility: existing projects without explicit harness default to `agy_superpowers`.
- Direct API keys stored on projects must never be exposed raw in HTTP response payloads; they must be masked or represented as boolean flags (`has_api_key`).
- Windows 11 environment: use PowerShell commands for shell operations.

---

### Task 1: Domain Entities & SQLite Persistence

**Files:**
- Modify: `painkiller/core/domain/models.py`
- Modify: `painkiller/adapters/issue_trackers/sqlite_tracker.py`
- Create/Modify: `tests/unit/test_project_model.py`

**Interfaces:**
- Consumes: `Project`, `BaseModel`, `ProjectRecord`
- Produces: `HarnessType(str, Enum)` (`AGY_SUPERPOWERS = "agy_superpowers"`, `DEEPSEEK_SUPERPOWERS = "deepseek_superpowers"`), `Project.harness`, `Project.api_key`, `Project.masked_api_key`

- [ ] **Step 1: Write failing tests for Project model with harness and api_key**

```python
# tests/unit/test_project_model.py
from painkiller.core.domain.models import Project, HarnessType

def test_project_harness_default():
    p = Project(id="proj-1", name="Test", repo_path="/tmp/test")
    assert p.harness == HarnessType.AGY_SUPERPOWERS
    assert p.api_key is None
    assert p.masked_api_key is None

def test_project_custom_harness_and_masked_api_key():
    p = Project(
        id="proj-2",
        name="DeepSeek Proj",
        repo_path="/tmp/test2",
        harness=HarnessType.DEEPSEEK_SUPERPOWERS,
        api_key="sk-1234567890abcdef",
    )
    assert p.harness == HarnessType.DEEPSEEK_SUPERPOWERS
    assert p.api_key == "sk-1234567890abcdef"
    assert p.masked_api_key == "sk-***cdef"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_project_model.py -v`  
Expected: FAIL (missing fields `harness`, `api_key`, `masked_api_key`)

- [ ] **Step 3: Implement domain model updates and SQLite schema migration**

In `painkiller/core/domain/models.py`:
```python
class HarnessType(str, Enum):
    AGY_SUPERPOWERS = "agy_superpowers"
    DEEPSEEK_SUPERPOWERS = "deepseek_superpowers"

class Project(BaseModel):
    ...
    harness: HarnessType = HarnessType.AGY_SUPERPOWERS
    api_key: Optional[str] = None

    @property
    def masked_api_key(self) -> Optional[str]:
        if not self.api_key:
            return None
        if len(self.api_key) <= 8:
            return "******"
        return f"{self.api_key[:3]}***{self.api_key[-4:]}"
```

In `painkiller/adapters/issue_trackers/sqlite_tracker.py`:
- Add `harness = Column(String, default="agy_superpowers", nullable=False)` and `api_key = Column(String, nullable=True)` to `ProjectRecord`.
- In `_migrate()` or SQLite connection init, check `PRAGMA table_info(projects)` and run `ALTER TABLE projects ADD COLUMN harness VARCHAR DEFAULT 'agy_superpowers'` and `ALTER TABLE projects ADD COLUMN api_key VARCHAR` if not present.
- Update `create_project` and `update_project` to store and update `harness` and `api_key`.
- Update `_to_project_domain` to map `harness` and `api_key`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_project_model.py tests/unit/test_sqlite_tracker.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add painkiller/core/domain/models.py painkiller/adapters/issue_trackers/sqlite_tracker.py tests/unit/test_project_model.py
git commit -m "feat(domain): add HarnessType, harness, and api_key to Project domain and SQLite tracker"
```

---

### Task 2: API Endpoints & Request/Response Serialization

**Files:**
- Modify: `painkiller/api/routes/projects.py`
- Modify: `tests/unit/test_projects_api.py` (or existing API test files)

**Interfaces:**
- Consumes: `CreateProjectRequest`, `UpdateProjectRequest`, `Project`
- Produces: API response with `harness`, `masked_api_key`, and `has_api_key`

- [ ] **Step 1: Write failing test for Project API serialization with harness and masked API key**

```python
# in test verifying project endpoints
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_project_with_harness(client: AsyncClient, auth_headers: dict):
    res = await client.post(
        "/api/projects",
        json={
            "name": "DSH Project",
            "purpose": "Testing DSH",
            "solution_description": "Solution",
            "harness": "deepseek_superpowers",
            "api_key": "sk-secret12345678",
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["harness"] == "deepseek_superpowers"
    # Never expose unmasked raw api_key
    assert "sk-secret12345678" not in str(data)
    assert data.get("has_api_key") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/ -k "test_create_project_with_harness" -v`  
Expected: FAIL

- [ ] **Step 3: Update `CreateProjectRequest`, `UpdateProjectRequest`, and response formatting in `projects.py`**

- In `CreateProjectRequest`:
  - `harness: Optional[str] = "agy_superpowers"`
  - `api_key: Optional[str] = None`
- In `UpdateProjectRequest`:
  - `harness: Optional[str] = None`
  - `api_key: Optional[str] = None`
- In project serialization helper or Pydantic response:
  - Add `has_api_key: bool` (`bool(p.api_key)`) and `masked_api_key: Optional[str]`.
  - Exclude `api_key` from public schema / JSON dump.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/ -k "test_create_project_with_harness" -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add painkiller/api/routes/projects.py tests/
git commit -m "feat(api): support harness and api_key in project creation and update routes"
```

---

### Task 3: Docker Images for DeepSeek Harness

**Files:**
- Create: `docker/deepseek-agent.Dockerfile`
- Create: `docker/deepseek-worker.Dockerfile`
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: `@deepseek-ai/dsh`, `superpowers`, `painkiller` CLI
- Produces: Docker images `painkiller-agent-deepseek:latest`, `painkiller-worker-deepseek:latest`

- [ ] **Step 1: Create `docker/deepseek-agent.Dockerfile`**

```dockerfile
# Imagem do agente de análise inicial: DeepSeek Harness (dsh) + superpowers
FROM node:22-slim

ARG SUPERPOWERS_REPO=https://github.com/obra/superpowers
ARG SUPERPOWERS_REF=main

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Instala o DeepSeek Harness nativo globalmente
RUN npm install -g @deepseek-ai/dsh

# Clona o repositório superpowers
RUN git clone --depth 1 --branch "${SUPERPOWERS_REF}" "${SUPERPOWERS_REPO}" /opt/superpowers \
    && rm -rf /opt/superpowers/.git

# Instala o CLI do painkiller (agent-run e ask)
COPY . /tmp/painkiller
RUN pip install --no-cache-dir --break-system-packages /tmp/painkiller && rm -rf /tmp/painkiller

RUN mkdir -p /workspace

WORKDIR /workspace

RUN git config --global user.name "Painkiller Agent" \
    && git config --global user.email "agent@painkiller.local" \
    && git config --global --add safe.directory /workspace

CMD ["painkiller", "agent-run", "--agent-bin", "dsh", "--stdin-file", "/workspace/.painkiller/agent-stdin.jsonl", "--", "--profile", "headless", "--json"]
```

- [ ] **Step 2: Create `docker/deepseek-worker.Dockerfile`**

```dockerfile
# Imagem do worker de execução de tarefas: DeepSeek Harness (dsh) + superpowers
FROM node:22-slim

ARG SUPERPOWERS_REPO=https://github.com/obra/superpowers
ARG SUPERPOWERS_REF=main

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @deepseek-ai/dsh

RUN git clone --depth 1 --branch "${SUPERPOWERS_REF}" "${SUPERPOWERS_REPO}" /opt/superpowers \
    && rm -rf /opt/superpowers/.git

COPY . /tmp/painkiller
RUN pip install --no-cache-dir --break-system-packages pytest /tmp/painkiller && rm -rf /tmp/painkiller

WORKDIR /workspace

RUN git config --global user.name "Painkiller Agent" \
    && git config --global user.email "agent@painkiller.local" \
    && git config --global --add safe.directory /workspace

CMD ["dsh", "--profile", "headless", "--json"]
```

- [ ] **Step 3: Update `docker-compose.yml`**

Add image build targets to `build` profile:
- `agent-deepseek-image` building `docker/deepseek-agent.Dockerfile`
- `worker-deepseek-image` building `docker/deepseek-worker.Dockerfile`
- Add `DEEPSEEK_API_KEY` to `api` service environment definitions.

- [ ] **Step 4: Commit**

```powershell
git add docker/deepseek-agent.Dockerfile docker/deepseek-worker.Dockerfile docker-compose.yml
git commit -m "feat(docker): add deepseek-agent and deepseek-worker Dockerfiles and compose services"
```

---

### Task 4: Dynamic Harness Execution in Docker Adapters

**Files:**
- Modify: `painkiller/adapters/sandbox/docker_agent_session.py`
- Modify: `painkiller/adapters/sandbox/docker_runner.py`
- Modify: `tests/unit/test_docker_agent_session.py`
- Modify: `tests/unit/test_docker_runner.py`

**Interfaces:**
- Consumes: `Project`, `HarnessType`, `FORWARDED_ENV`
- Produces: Dynamic image dispatch (`painkiller-agent` vs `painkiller-agent-deepseek`), dynamic env injection (`GEMINI_API_KEY` vs `DEEPSEEK_API_KEY`), and `parse_agent_line` mapping for DSH events

- [ ] **Step 1: Write failing tests for harness-based image and env resolution**

```python
# tests/unit/test_docker_agent_session.py
import pytest
from painkiller.core.domain.models import HarnessType

def test_docker_agent_session_resolves_deepseek_harness(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-global")
    # Test that when harness == DEEPSEEK_SUPERPOWERS, image is painkiller-agent-deepseek:latest
    # and DEEPSEEK_API_KEY is forwarded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_docker_agent_session.py -k "deepseek" -v`  
Expected: FAIL

- [ ] **Step 3: Implement dynamic harness resolution and event parsing**

In `painkiller/adapters/sandbox/docker_agent_session.py`:
- Accept `harness: HarnessType = HarnessType.AGY_SUPERPOWERS` and `api_key: Optional[str] = None` in `start()`.
- Add `DEEPSEEK_API_KEY` to forwarded environment list.
- If `harness == HarnessType.DEEPSEEK_SUPERPOWERS`:
  - Select `image_name = "painkiller-agent-deepseek:latest"`.
  - Resolve `deepseek_key = api_key or env_vars.get("DEEPSEEK_API_KEY")`.
  - Validate: raise `RuntimeError("DEEPSEEK_API_KEY não está definida...")` if missing.
  - Command: `["painkiller", "agent-run", "--agent-bin", "dsh", "--stdin-file", "/workspace/" + STDIN_RELATIVE, "--idle-timeout", str(timeout_seconds), "--", "--profile", "headless", "--json"]`.
- Update `parse_agent_line` to handle JSON events from `dsh` (streaming text chunk -> `ASSISTANT_DELTA`, tool use -> `TOOL_USE`, tool result -> `TOOL_RESULT`, done -> `RESULT`).

In `painkiller/adapters/sandbox/docker_runner.py`:
- Check `project.harness`:
  - If `deepseek_superpowers`: use `painkiller-worker-deepseek:latest` and command `["dsh", "--profile", "headless", "--json", task_instructions]`.
  - Inject resolved `DEEPSEEK_API_KEY`.
- Maintain clean interruption check (exit 42 / `.painkiller/clarification.json`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_docker_agent_session.py tests/unit/test_docker_runner.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add painkiller/adapters/sandbox/docker_agent_session.py painkiller/adapters/sandbox/docker_runner.py tests/unit/
git commit -m "feat(sandbox): implement dynamic harness dispatch and credentials injection for deepseek and agy"
```

---

### Task 5: Frontend UI - ProjectDialog Harness & API Key Selection

**Files:**
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/lib/components/ProjectDialog.svelte`

**Interfaces:**
- Consumes: `api.createProject`, `api.updateProject`, `Project`
- Produces: UI selector for `harness` (`agy_superpowers` | `deepseek_superpowers`) and reactive `api_key` input

- [ ] **Step 1: Update TypeScript types in `web/src/lib/types.ts`**

```typescript
export type HarnessType = 'agy_superpowers' | 'deepseek_superpowers';

export interface Project {
  ...
  harness?: HarnessType;
  has_api_key?: boolean;
}
```

- [ ] **Step 2: Update `ProjectDialog.svelte`**

- Add state variables:
  ```typescript
  let harness = $state<HarnessType>('agy_superpowers');
  let apiKey = $state('');
  ```
- Reset in `$effect`:
  ```typescript
  harness = project?.harness ?? 'agy_superpowers';
  apiKey = '';
  ```
- In HTML form, add:
  - Radio/segmented selection for Harness with label "Harness do Agente":
    - Option 1: `Antigravity CLI (agy) + Superpowers` (`agy_superpowers`)
    - Option 2: `DeepSeek Harness (dsh) + Superpowers` (`deepseek_superpowers`)
  - API Key input field with dynamic label:
    - If `agy_superpowers`: "Chave de API Google Gemini (Opcional)"
    - If `deepseek_superpowers`: "Chave de API DeepSeek (Opcional)"
    - Helper text: "Deixe em branco para utilizar a chave global configurada no servidor (.env)."
- In `save()`, pass `harness` and `api_key: apiKey.trim() || undefined` to `api.createProject` or `api.updateProject`.

- [ ] **Step 3: Run frontend type checks and test build**

```powershell
cd web; npm run check; npm run build; cd ..
```
Expected: 0 errors in `svelte-check` and successful build.

- [ ] **Step 4: Commit**

```powershell
git add web/src/lib/types.ts web/src/lib/components/ProjectDialog.svelte painkiller/api/static/
git commit -m "feat(ui): add harness selection and api key configuration to ProjectDialog"
```

---

### Task 6: End-to-End Test Suite Verification

**Files:**
- Run full pytest suite: `pytest`
- Run frontend checks: `cd web; npm run check; cd ..`

- [ ] **Step 1: Run full Python test suite**

Run: `pytest`  
Expected: All tests pass (0 failures).

- [ ] **Step 2: Run frontend typecheck**

Run: `cd web; npm run check; cd ..`  
Expected: 0 errors.

- [ ] **Step 3: Final Commit and Documentation update**

```powershell
git add CLAUDE.md README.md
git commit -m "docs: document multi-harness selection (agy and deepseek) and api key precedence"
```
