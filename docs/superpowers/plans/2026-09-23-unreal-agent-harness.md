# Unreal Agent + Superpowers + DeepSeek Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the [Unreal Agent](https://github.com/unreallabsai/unreal-agent) harness (`unreal_superpowers`) into Painkiller, powered by the DeepSeek provider (`DEEPSEEK_API_KEY`) and Superpowers skills, across domain models, Docker adapters, execution bridges, Dockerfiles and SvelteKit UI.

**Architecture:** Add `HarnessType.UNREAL_SUPERPOWERS` sharing `DEEPSEEK_KEY_HARNESSES`. Provide `painkiller unreal-run` to bridge interactive analysis messages and map Unreal Agent's JSONL session items to Painkiller's `AgentEvent` stream. Provide Dockerfiles in `docker/` building `unreal-agent-runner` with Go and wiring `.harness/skills` to Superpowers. Update SvelteKit's project dialog and status badges.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, Click, Docker (multi-stage Go 1.24 + Debian), SvelteKit, TypeScript.

**Spec:** `docs/superpowers/specs/2026-09-23-unreal-agent-harness-design.md`

## Global Constraints

- OS: Windows 11 with PowerShell terminal for host commands.
- Python: >=3.11, async-first with asyncio.
- Authentication: Shared DeepSeek key via `project.api_key` or fallback to `.env` (`DEEPSEEK_API_KEY`).
- Model Presets: `deepseek/deepseek-v4-pro` (default), `deepseek/deepseek-v4-flash`, `deepseek/deepseek-flash`, plus custom models.
- Exit 42: Support `painkiller ask` clean interruption for analyst clarifications.
- Skills: `.harness/skills` in workspace linked to Superpowers (`/opt/superpowers/skills`).

---

### Task 1: Domain Model and Persistence (`HarnessType.UNREAL_SUPERPOWERS`)

**Files:**
- Modify: `painkiller/core/domain/models.py:134-140`
- Modify: `tests/unit/test_project_model.py:80-98`

**Interfaces:**
- Consumes: `HarnessType` enum in `painkiller.core.domain.models`
- Produces: `HarnessType.UNREAL_SUPERPOWERS = "unreal_superpowers"`

- [ ] **Step 1: Write failing test in `test_project_model.py`**

In `tests/unit/test_project_model.py`, add test verifying `HarnessType.UNREAL_SUPERPOWERS`:
```python
    p4 = await tracker.create_project(
        name="Unreal Agent Project",
        repo_path="/tmp/p4",
        harness=HarnessType.UNREAL_SUPERPOWERS,
        model="deepseek/deepseek-v4-pro",
    )
    assert p4.harness == HarnessType.UNREAL_SUPERPOWERS
    assert p4.model == "deepseek/deepseek-v4-pro"

    loaded_p4 = await tracker.get_project(p4.id)
    assert loaded_p4 is not None
    assert loaded_p4.harness == HarnessType.UNREAL_SUPERPOWERS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_project_model.py -v`
Expected: FAIL with AttributeError: UNREAL_SUPERPOWERS is not a valid HarnessType

- [ ] **Step 3: Update `HarnessType` enum in `models.py`**

Add `UNREAL_SUPERPOWERS = "unreal_superpowers"` to `HarnessType` in `painkiller/core/domain/models.py`:
```python
class HarnessType(str, Enum):
    """Supported agent harnesses."""
    AGY_SUPERPOWERS = "agy_superpowers"
    DEEPSEEK_SUPERPOWERS = "deepseek_superpowers"
    MAKI_SUPERPOWERS = "maki_superpowers"
    UNREAL_SUPERPOWERS = "unreal_superpowers"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_project_model.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add painkiller/core/domain/models.py tests/unit/test_project_model.py
git commit -m "feat(domain): adicionar HarnessType.UNREAL_SUPERPOWERS"
```

---

### Task 2: CLI Bridge `painkiller unreal-run` and Event Parser

**Files:**
- Create: `painkiller/cli/unreal_run.py`
- Modify: `painkiller/cli/main.py:1-22`
- Create: `tests/unit/test_unreal_harness.py`

**Interfaces:**
- Consumes: `.painkiller/agent-stdin.jsonl`, `unreal-agent-runner` executable
- Produces: `painkiller unreal-run` CLI command emitting `stream-json` / `AgentEvent` lines to stdout

- [ ] **Step 1: Write failing test in `tests/unit/test_unreal_harness.py`**

Test the parser and translation of `unreal-agent`'s session items (`model_response`, `tool_call_status`, `error`) into `AgentEvent`:
```python
import pytest
from painkiller.cli.unreal_run import parse_unreal_line
from painkiller.core.domain.models import AgentEventType

def test_parse_unreal_model_response():
    line = '{"Kind": "model_response", "Data": {"TurnID": "t1", "Response": {"Output": [{"Type": "message", "Data": {"Role": "assistant", "Text": "Olá, analista!"}}], "Usage": {"InputTokens": 10, "OutputTokens": 5}}}}'
    events = parse_unreal_line(line)
    assert len(events) == 2
    assert events[0].type == AgentEventType.ASSISTANT
    assert events[0].text == "Olá, analista!"
    assert events[1].type == AgentEventType.RESULT

def test_parse_unreal_tool_call():
    line = '{"Kind": "model_response", "Data": {"TurnID": "t1", "Response": {"Output": [{"Type": "tool_call", "Data": {"CallID": "c1", "Name": "bash", "Arguments": "ls -la"}}]}}}'
    events = parse_unreal_line(line)
    assert len(events) == 1
    assert events[0].type == AgentEventType.TOOL_USE
    assert events[0].text == "bash"

def test_parse_unreal_error():
    line = '{"type": "error", "message": "authentication failed: invalid key"}'
    events = parse_unreal_line(line)
    assert len(events) == 1
    assert events[0].type == AgentEventType.ERROR
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_unreal_harness.py -v`
Expected: FAIL with ModuleNotFoundError or ImportError

- [ ] **Step 3: Implement `painkiller/cli/unreal_run.py` and register in `painkiller/cli/main.py`**

Implement `parse_unreal_line` and the `unreal_run` command:
- Reads `--stdin-file` and polls for new lines until `EOF_SENTINEL`.
- For each message, executes `unreal-agent-runner -workspace <workspace> -session-directory <session_dir>` with `-p <prompt>` (or JSON with `session_id`).
- Pipes output lines through `parse_unreal_line` and writes normalized JSON lines to stdout.
- Register `unreal_run` in `painkiller/cli/main.py`: `cli.add_command(unreal_run, name="unreal-run")`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_unreal_harness.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add painkiller/cli/unreal_run.py painkiller/cli/main.py tests/unit/test_unreal_harness.py
git commit -m "feat(cli): implementar painkiller unreal-run e parser de eventos do unreal-agent"
```

---

### Task 3: Sandbox Adapters Integration (`DockerAgentSession` & `DockerSandboxRunner`)

**Files:**
- Modify: `painkiller/adapters/sandbox/docker_agent_session.py:50-250,510-570`
- Modify: `painkiller/adapters/sandbox/docker_runner.py:80-150`
- Modify: `tests/unit/test_unreal_harness.py`

**Interfaces:**
- Consumes: `HarnessType.UNREAL_SUPERPOWERS`, `Project.harness`, `Project.api_key`
- Produces: Docker container execution targeting `painkiller-agent-unreal:latest` and `painkiller-worker-unreal:latest`

- [ ] **Step 1: Write failing tests in `tests/unit/test_unreal_harness.py`**

Add tests for `DockerAgentSession.start()` and `DockerSandboxRunner.run_task()` with `harness="unreal_superpowers"`:
```python
async def test_start_runs_unreal_in_session_mode(tmp_path, client):
    session = DockerAgentSession(client=client)
    await session.start(
        "analysis-unreal", str(tmp_path), "Comece", claude_session_id=SESSION,
        harness="unreal_superpowers", api_key="sk-project",
    )
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["image"] == "painkiller-agent-unreal:latest"
    command = kwargs["command"]
    assert command[:2] == ["painkiller", "unreal-run"]
    assert kwargs["environment"]["DEEPSEEK_API_KEY"] == "sk-project"
    assert kwargs["environment"]["UNREAL_HARNESS_LLM_PROVIDER"] == "openai"
    assert kwargs["environment"]["UNREAL_HARNESS_LLM_BASE_URL"] == "https://api.deepseek.com"
    binds = {v["bind"] for v in kwargs["volumes"].values()}
    assert binds == {"/workspace", "/root/.local/state/unreal-agent"}

async def test_runner_runs_unreal_one_shot():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_unreal_harness.py -k test_start_runs_unreal_in_session_mode -v`
Expected: FAIL

- [ ] **Step 3: Implement Docker adapter logic for `unreal_superpowers`**

In `painkiller/adapters/sandbox/docker_agent_session.py`:
- Add `"unreal_superpowers"` to `DEEPSEEK_KEY_HARNESSES`.
- In `DockerAgentSession.start()`, add branch for `harness_type == "unreal_superpowers"`:
  - image: `os.environ.get("PAINKILLER_AGENT_UNREAL_IMAGE") or "painkiller-agent-unreal:latest"`
  - Configure environment: `DEEPSEEK_API_KEY`, `UNREAL_HARNESS_LLM_API_KEY`, `UNREAL_HARNESS_LLM_PROVIDER`, `UNREAL_HARNESS_LLM_BASE_URL`, `UNREAL_HARNESS_LLM_MODEL`.
  - Bind mounts: `/workspace` and `.painkiller/unreal_home` -> `/root/.local/state/unreal-agent`.
  - Command: `painkiller unreal-run --stdin-file /workspace/.painkiller/agent-stdin.jsonl --session-id <claude_session_id>`.
- In `painkiller/adapters/sandbox/docker_runner.py`:
  - In `run_task()`, add branch for `harness_type == "unreal_superpowers"`:
  - image: `os.environ.get("PAINKILLER_WORKER_UNREAL_IMAGE") or "painkiller-worker-unreal:latest"`
  - command: `unreal-agent-runner -workspace /workspace -p <task_instructions>`
- In `parse_agent_line`:
  - Ensure lines with `Kind` (`model_response`, `tool_call_status`) are parsed directly if encountered from worker container logs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_unreal_harness.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add painkiller/adapters/sandbox/docker_agent_session.py painkiller/adapters/sandbox/docker_runner.py tests/unit/test_unreal_harness.py
git commit -m "feat(sandbox): suportar unreal_superpowers em DockerAgentSession e DockerSandboxRunner"
```

---

### Task 4: Dockerfiles (`docker/unreal-agent.Dockerfile` & `docker/unreal-worker.Dockerfile`)

**Files:**
- Create: `docker/unreal-agent.Dockerfile`
- Create: `docker/unreal-worker.Dockerfile`
- Modify: `docker-compose.yml:50-80`

**Interfaces:**
- Produces: `painkiller-agent-unreal:latest` and `painkiller-worker-unreal:latest` image definitions

- [ ] **Step 1: Create `docker/unreal-agent.Dockerfile`**

Multi-stage build:
- Stage 1: Build `unreal-agent-runner` with Go from github.com/unreallabsai/unreal-agent.
- Stage 2: Runtime image based on `debian:trixie-slim` (or `node:22-slim`/python3) with git, curl, python3, pip.
- Clone Superpowers to `/opt/superpowers`.
- Setup `/root/.agents` and symlink `.harness/skills` support.
- Install Painkiller package (`pip install /tmp/painkiller`).
- Default CMD: `["painkiller", "unreal-run", "--stdin-file", "/workspace/.painkiller/agent-stdin.jsonl"]`.

- [ ] **Step 2: Create `docker/unreal-worker.Dockerfile`**

Same base with pytest, pytest-asyncio, lxml, and painkiller CLI for task verification and clean interruption.

- [ ] **Step 3: Update `docker-compose.yml`**

Add image build sections or service reference notes for `painkiller-agent-unreal` and `painkiller-worker-unreal`.

- [ ] **Step 4: Commit**

```bash
git add docker/unreal-agent.Dockerfile docker/unreal-worker.Dockerfile docker-compose.yml
git commit -m "chore(docker): criar Dockerfiles para painkiller-agent-unreal e painkiller-worker-unreal"
```

---

### Task 5: Frontend SvelteKit Integration

**Files:**
- Modify: `web/src/lib/types.ts:15-25`
- Modify: `web/src/lib/components/ProjectDialog.svelte:25-60,300-345`
- Modify: `web/src/routes/projetos/+page.svelte:135-150`
- Modify: `web/src/routes/projetos/[id]/+layout.svelte:10-15`

**Interfaces:**
- Consumes: `HarnessType` definition
- Produces: UI options and model selectors for `unreal_superpowers`

- [ ] **Step 1: Update `web/src/lib/types.ts`**

Update `HarnessType` and `DEEPSEEK_KEY_HARNESSES`:
```typescript
export type HarnessType = 'agy_superpowers' | 'deepseek_superpowers' | 'maki_superpowers' | 'unreal_superpowers';

export const DEEPSEEK_KEY_HARNESSES: readonly HarnessType[] = [
  'deepseek_superpowers',
  'maki_superpowers',
  'unreal_superpowers'
];
```

- [ ] **Step 2: Update `ProjectDialog.svelte`**

- Add `unreal_superpowers` presets in `MODEL_PRESETS`:
```typescript
    unreal_superpowers: [
      { id: 'deepseek/deepseek-v4-pro', label: 'deepseek/deepseek-v4-pro (Padrão / Recomendado)' },
      { id: 'deepseek/deepseek-v4-flash', label: 'deepseek/deepseek-v4-flash' },
      { id: 'deepseek/deepseek-flash', label: 'deepseek/deepseek-flash' }
    ]
```
- Add the radio option card in `ProjectDialog.svelte`:
```svelte
          <label class="radio-card" class:active={harness === 'unreal_superpowers'}>
            <input
              type="radio"
              name="harness"
              value="unreal_superpowers"
              bind:group={harness}
            />
            <div class="radio-info">
              <span class="radio-title">Unreal Agent + Superpowers</span>
              <span class="radio-desc">DeepSeek V4 via unreal-agent (Go async harness)</span>
            </div>
          </label>
```

- [ ] **Step 3: Update `+page.svelte` and `+layout.svelte`**

Add badge label `unreal` in `/projetos` and layout map in `/projetos/[id]`.

- [ ] **Step 4: Run typecheck**

Run in `web/`: `npm run check`
Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/types.ts web/src/lib/components/ProjectDialog.svelte web/src/routes/projetos/+page.svelte web/src/routes/projetos/[id]/+layout.svelte
git commit -m "feat(web): adicionar suporte ao harness Unreal Agent + Superpowers no frontend"
```

---

### Task 6: Full Verification and Documentation Update

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Test: All tests in `tests/`

- [ ] **Step 1: Run complete test suite**

Run: `pytest`
Expected: All tests pass.

- [ ] **Step 2: Update documentation**

Document `unreal_superpowers` in `CLAUDE.md` and `README.md` detailing the async-first Go harness, provider settings, and Superpowers skills integration.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: documentar novo harness unreal_superpowers"
```
