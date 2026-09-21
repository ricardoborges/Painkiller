# Antigravity CLI + Superpowers + Gemini 3.8 Flash Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the initial analysis agent harness to run Google Antigravity CLI (`agy`) with the `superpowers` plugin and Google's `gemini-3.8-flash` model, configured via `GEMINI_API_KEY` in `.env`.

**Architecture:** Replace the Claude Code container runtime with a native `agy` container runtime. The interactive bridge (`agent-run`) feeds NDJSON turns formatted for `agy` (`{"event": "user", ...}`), while `DockerAgentSession` invokes `agy` in headless mode with `--input-format stream-json --output-format stream-json --dangerously-skip-permissions --model gemini-3.8-flash --effort medium`. Events emitted by `agy` are parsed into domain `AgentEvent`s in real-time.

**Tech Stack:** Python 3.11, Docker, Google Antigravity CLI (`agy`), Superpowers plugin, FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-antigravity-harness-design.md`

## Global Constraints

- OS is Windows 11 with PowerShell terminal for host commands.
- Code identifiers and docstrings in English; user copy, prompts and error messages in pt-BR.
- Strict backward compatibility for the event streaming contract (`AgentEvent` lifecycle: `ASSISTANT_DELTA`, `THINKING_DELTA`, `TOOL_USE`, `TOOL_RESULT`, `RESULT`, `EXIT`).
- API key must be read exclusively from `.env` via `python-dotenv` / `os.environ["GEMINI_API_KEY"]`.

---

### Task 1: Update CLI bridge (`painkiller/cli/agent_run.py`)

**Files:**
- Modify: `painkiller/cli/agent_run.py:25-35`
- Test: `tests/unit/test_agent_bridge.py`

**Interfaces:**
- Consumes: Click CLI options.
- Produces: CLI command `painkiller agent-run --agent-bin agy ...`.

- [ ] **Step 1: Write/update test for default agent-bin in agent_run**

```python
from click.testing import CliRunner
from painkiller.cli.agent_run import agent_run

def test_agent_run_default_bin_is_agy(tmp_path):
    runner = CliRunner()
    # Test that default option is agy
    stdin_file = tmp_path / "stdin.jsonl"
    stdin_file.touch()
    result = runner.invoke(agent_run, ["--help"])
    assert "default: agy" in result.output or "default='agy'" in result.output or "agy" in result.output
```

- [ ] **Step 2: Run test to verify behavior**

Run: `pytest tests/unit/test_agent_bridge.py -v`

- [ ] **Step 3: Modify `painkiller/cli/agent_run.py`**

Update line 27:
```python
@click.option("--agent-bin", default="agy", help="Executable to run as the agent.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_agent_bridge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add painkiller/cli/agent_run.py tests/unit/test_agent_bridge.py
git commit -m "feat(cli): mudar agent-bin padrao para agy"
```

---

### Task 2: Adapt `DockerAgentSession` and `parse_agent_line` for `agy` and Gemini 3.8 Flash

**Files:**
- Modify: `painkiller/adapters/sandbox/docker_agent_session.py`
- Test: `tests/unit/test_docker_agent_session.py`

**Interfaces:**
- Consumes: `GEMINI_API_KEY`, `GOOGLE_API_KEY` from environment.
- Produces: `DockerAgentSession.start()` executing `agy` with stream-json, `--model gemini-3.8-flash`, `--effort medium`, `--dangerously-skip-permissions`.
- Produces: `parse_agent_line()` parsing `agy` events (`init`, `step_update`, `result`).

- [ ] **Step 1: Update unit tests in `tests/unit/test_docker_agent_session.py`**

Add tests for:
- Missing `GEMINI_API_KEY` raises `RuntimeError` naming `GEMINI_API_KEY`.
- Presence of `GEMINI_API_KEY` starts container with `agy` flags (`--model`, `gemini-3.8-flash`, `--effort`, `medium`, `--dangerously-skip-permissions`, `--input-format`, `stream-json`, `--output-format`, `stream-json`).
- `parse_agent_line` correctly maps `agy` event lines:
  - `{"event": "step_update", "step_update": {"step_type": "agent_response", "text_delta": "Olá!"}}` -> `AgentEventType.ASSISTANT_DELTA`
  - `{"event": "step_update", "step_update": {"step_type": "tool", "tool_name": "list_dir", "state": "ACTIVE"}}` -> `AgentEventType.TOOL_USE`
  - `{"event": "result", "result": {"status": "SUCCESS", "response": "Pronto"}}` -> `AgentEventType.RESULT`

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_docker_agent_session.py -v`
Expected: FAIL

- [ ] **Step 3: Implement changes in `painkiller/adapters/sandbox/docker_agent_session.py`**

- Add `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `PAINKILLER_AGENT_EFFORT` to `FORWARDED_ENV`.
- Update `_require_credentials` to require `GEMINI_API_KEY` or `GOOGLE_API_KEY`.
- Set default model to `os.environ.get("PAINKILLER_AGENT_MODEL") or "gemini-3.8-flash"`.
- Set default effort to `os.environ.get("PAINKILLER_AGENT_EFFORT") or "medium"`.
- Assemble command with `agy`, `--model`, `--effort`, `--dangerously-skip-permissions`, `--input-format stream-json`, `--output-format stream-json`.
- Mount `/root/.gemini` instead of `/home/node/.claude`.
- Update `send` to emit `{"event": "user", "type": "user", "message": {"role": "user", "content": text}}`.
- Update `parse_agent_line` to handle `event in ("init", "step_update", "result")` alongside legacy Claude events.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_docker_agent_session.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add painkiller/adapters/sandbox/docker_agent_session.py tests/unit/test_docker_agent_session.py
git commit -m "feat(agent): refatorar DockerAgentSession para Antigravity CLI e Gemini 3.8 Flash"
```

---

### Task 3: Update `docker/agent.Dockerfile`

**Files:**
- Modify: `docker/agent.Dockerfile`

**Interfaces:**
- Produces: Docker image `painkiller-agent:latest` containing `agy`, `superpowers` plugin registered, and `painkiller` CLI.

- [ ] **Step 1: Edit `docker/agent.Dockerfile`**

Install `agy` using the official curl installer with `-d /usr/local/bin`, clone `superpowers`, ensure `plugin.json` exists, copy into `/root/.gemini/config/plugins/superpowers`, and register via `agy plugin install /opt/superpowers`.

- [ ] **Step 2: Validate dockerfile syntax and commands**

- [ ] **Step 3: Commit**

```bash
git add docker/agent.Dockerfile
git commit -m "feat(docker): atualizar agent.Dockerfile para instalar agy e superpowers"
```

---

### Task 4: Update `.env` and `docker-compose.yml`

**Files:**
- Modify: `.env`
- Modify: `docker-compose.yml`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update `.env`**

Ensure `GEMINI_API_KEY` is documented, and set:
`PAINKILLER_AGENT_MODEL=gemini-3.8-flash`
`PAINKILLER_AGENT_EFFORT=medium`

- [ ] **Step 2: Update `docker-compose.yml`**

Pass `GEMINI_API_KEY: ${GEMINI_API_KEY:-}` and `PAINKILLER_AGENT_EFFORT: ${PAINKILLER_AGENT_EFFORT:-medium}` to the `api` service environment.

- [ ] **Step 3: Update `CLAUDE.md`**

Update documentation describing the initial analysis agent running Antigravity CLI (`agy`) with Superpowers and Gemini 3.8 Flash.

- [ ] **Step 4: Commit**

```bash
git add .env docker-compose.yml CLAUDE.md
git commit -m "chore(config): atualizar env vars e docker-compose para Antigravity CLI e Gemini 3.8 Flash"
```

---

### Task 5: Full Test Suite Verification

**Files:**
- Test: All tests in `tests/`

- [ ] **Step 1: Run complete test suite**

Run: `pytest --import-mode=importlib`
Expected: 68+ tests passing with 0 failures.

- [ ] **Step 2: Final commit if needed**
