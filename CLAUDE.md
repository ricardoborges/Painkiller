# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Painkiller is a platform that automates software development by orchestrating coding agents inside Docker containers. An analyst is interviewed by a containerized agent running the superpowers `brainstorming` skill, the resulting spec is decomposed into atomic tasks, and each task is dispatched to a sandboxed agent running superpowers skills on a feature branch.

**Multi-Harness Agent Ecosystem.** Each project can be configured with its preferred harness:
1. **Antigravity CLI (`agy`) + Superpowers**: Powered by Google's **Gemini 3.8 Flash** with the **Superpowers** plugin.
2. **DeepSeek Harness (`dsh`) + Superpowers**: Powered by **DeepSeek V4** (`deepseek-v4-flash` by default) using the official `@deepseek-ai/dsh` harness. See **DeepSeek harness** below.
3. **Maki (`maki`) + Superpowers**: [maki.sh](https://maki.sh), a Rust coding agent, on **DeepSeek V4** with the **same DeepSeek key** as option 2. See **Maki harness** below.
**Model and effort are per project too** (`Project.model`, `Project.effort`), picked in the project form (`ProjectForm.svelte`, pages `/projects/new` and `/projects/[id]/edit`) for the chosen harness; nothing reads `PAINKILLER_AGENT_MODEL`/`_EFFORT`, `PAINKILLER_DEEPSEEK_*`, `PAINKILLER_MAKI_MODEL` or `PAINKILLER_UNREAL_MODEL` any more. `harness_model()` / `harness_effort()` in `core/domain/models.py` fill the gaps with `HARNESS_DEFAULT_MODELS` (the form's first preset) and `medium`. Effort exists only for `EFFORT_HARNESSES` (agy's `--effort`, dsh's `reasoning_effort`); for Maki and Unreal it is dropped, and switching a project to one of them clears it.

Every project **must** have its own API key (`api_key`) for its harness's provider — there is no server-wide fallback: `create_project` answers 400 without one, `dispatch_task` and `DockerAgentSession.start` refuse a project without one, and neither docker adapter forwards `GEMINI_API_KEY`/`DEEPSEEK_API_KEY` from the server environment any more. The provider family is `key_provider(harness)` in `core/domain/models.py` (`DEEPSEEK_KEY_HARNESSES` lives there too): `dsh`, `maki` and `unreal` share the DeepSeek key, so switching between them keeps it, while switching to or from `agy` makes `PUT /api/projects/{id}` demand a new key. `POST /api/projects/validate-key` asks the provider (`adapters/llm/balance.py:validate_key`, swappable as `app.state.key_validator`); the form blocks only on an explicit refusal.

Code comments, LLM prompts, API error messages and the UI are in **Portuguese (pt-BR)**; code identifiers, docstrings and **URL routes / query params** are in English (`/projects/[id]/initial-analysis`, `/admin/settings`, `?new=`), even when the visible label is Portuguese. Follow that split.

## Commands

```bash
pip install -e ".[dev]"           # install package + test deps
pytest                             # full suite (no Docker daemon needed — docker is mocked)
pytest tests/unit/test_orchestrator.py::test_dispatch_task_success   # single test
uvicorn painkiller.api.server:app --reload    # API + built UI at http://localhost:8000/
# AGY Images:
docker build -f docker/worker.Dockerfile -t painkiller-worker:latest .
docker build -f docker/agent.Dockerfile -t painkiller-agent:latest .
# DeepSeek Harness Images:
docker build -f docker/deepseek-worker.Dockerfile -t painkiller-worker-deepseek:latest .
docker build -f docker/deepseek-agent.Dockerfile -t painkiller-agent-deepseek:latest .
# Maki Images:
docker build -f docker/maki-worker.Dockerfile -t painkiller-worker-maki:latest .
docker build -f docker/maki-agent.Dockerfile -t painkiller-agent-maki:latest .
```

Frontend (`web/`, SvelteKit — see **Frontend** below):

```bash
cd web
npm install
npm run dev        # :5173, proxies /api to uvicorn on :8000 — run both
npm run build      # emits the SPA into painkiller/api/static/
npm run check      # svelte-check; must stay at 0 errors
```

`uvicorn` alone serves the **last build**, not your working copy — edits under `web/src/` are invisible until `npm run build` or `npm run dev`.

Whole stack in Docker (see **Container topology** below):

```bash
docker network create coolify           # once per machine — see below
docker compose --profile build build    # api image + painkiller-worker + painkiller-agent
docker compose up -d                    # api on :8000; the *-image services never start
docker compose logs -f api
docker compose down
```

`pyproject.toml` sets `asyncio_mode = "auto"` and `pythonpath = ["."]`, so async tests need no event-loop boilerplate and the package is importable without install.

There is no linter or formatter configured.

## Configuration

**Env zero.** The platform needs no `.env`: there is no `.env.example`, the run scripts create none, and compose loads one only if it exists (`required: false`). Everything an operator sets — administrator, session-signing key, session lifetime, public URL, host path of `./storage`, Google sign-in, Coolify, the Gitea service-account password — lives **only** in the database (see **Setup wizard and platform settings**); models, effort and LLM keys live on each project. What is still read from the environment are optional infrastructure overrides with compose/code defaults (`PAINKILLER_DB_URL`, image names, `PAINKILLER_AGENT_NETWORK`, `PAINKILLER_GITEA_PORT`, `COOLIFY_PORT`, `PAINKILLER_TASK_TIMEOUT`, internal URLs). If a `.env` exists, [server.py](painkiller/api/server.py) loads it with `override=True` at import time, so it wins over the shell and needs a restart.

LLM selection resolves through [litellm_adapter.py](painkiller/adapters/llm/litellm_adapter.py) in this order: `PAINKILLER_LLM_MODEL` / `PAINKILLER_LLM_API_BASE` / `PAINKILLER_LLM_API_KEY`, then provider-specific vars (`NVIDIA_API_KEY`, `OPENAI_API_BASE`, `OPENAI_API_KEY`). When the key starts with `nvapi-` or the base URL contains `nvidia.com`, the adapter bypasses LiteLLM entirely and streams SSE against NVIDIA Build NIM via httpx (`_complete_nvidia`) — that path exists because reasoning models there need streaming and long timeouts. Default model is `moonshotai/kimi-k3`.

Two dependencies are imported but **not** declared in `pyproject.toml`: `python-dotenv` (required by the server) and `httpx` (dev-only extra, but used at runtime by the NVIDIA path and the provider-balance lookup). `pypdf` and `python-docx` are optional — [attachment_reader.py](painkiller/core/attachment_reader.py) degrades gracefully without them.

## Architecture

Hexagonal / ports & adapters. The dependency rule is strict: `core/` and `engine/` import only from `core/`; adapters implement the ABCs in [core/ports/](painkiller/core/ports/); wiring happens only in `create_app()`.

- **[core/domain/models.py](painkiller/core/domain/models.py)** — Pydantic entities (`Project`, `Task`, `ClarificationRequest`, `ExecutionResult`) plus the `TaskStatus` lifecycle: `BACKLOG → READY → RUNNING → {AWAITING_ANALYST | IN_REVIEW | FAILED} → COMPLETED`.
- **[core/ports/](painkiller/core/ports/)** — ABCs: `IssueTrackerPort`, `SandboxPort`, `AgentSessionPort`, `GitPort`, `LLMPort`, `UsageLedgerPort`, `UserDirectoryPort`, `DeploymentPort`, `PlatformSettingsPort`. Adding a method here means updating the adapter *and* the `AsyncMock`-based unit tests.
- **[adapters/](painkiller/adapters/)** — `sqlite_tracker` (async SQLAlchemy; list fields are stored as JSON text columns and converted in `_to_task_domain`/`_to_project_domain`), `git_adapter` (shells out to `git`), `docker_runner` (docker-py, one-shot), `docker_agent_session` (docker-py, long-lived), `litellm_adapter`. The container-to-host path rewrite both docker adapters need lives in `sandbox/paths.py`.
- **[engine/orchestrator.py](painkiller/engine/orchestrator.py)** — the state machine. Everything below hangs off it.
- **[engine/analysis.py](painkiller/engine/analysis.py)** — the interactive initial analysis (see **Initial analysis** below). `self.runs` is a cache over the tracker, not the source of truth.
- **[interrogation/wizard.py](painkiller/interrogation/wizard.py)** — the *older* LLM interview + backlog generation, still wired at `/api/interrogation/*` but no longer reachable from the UI. **Sessions live in an in-process dict**, so they are lost on restart and will not survive multiple workers.
- **[api/](painkiller/api/)** — FastAPI. Adapters are instantiated in `create_app()` and reached from handlers via `request.app.state.<name>`; tests override by passing a temp `db_url` to `create_app()`.
- **[api/static/](painkiller/api/static/)** — **generated**, never hand-edited. It is the SvelteKit build output, committed so that a clone can run `uvicorn` with no Node toolchain. The source is `web/`.

### Clean-interruption protocol (exit code 42)

The distinguishing mechanism of this codebase. When the agent in the container hits ambiguity, its prompt tells it to run `painkiller ask "<question>" --context "<where>"` instead of guessing. That CLI ([cli/ask.py](painkiller/cli/ask.py)) writes `.painkiller/clarification.json` into the workspace, `git add -A && git commit` the WIP, and exits **42**.

`DockerSandboxRunner` sees exit 42, reads that JSON back off the bind-mounted repo path, and returns it as `ExecutionResult.clarification`. The orchestrator then records the clarification, sets the task to `AWAITING_ANALYST`, and stops. `POST /api/tasks/{id}/clarification` resolves it and re-enters `dispatch_task` from the top — the task re-runs on the same branch with the WIP commit already in place.

So exit codes carry meaning end to end: `42` = paused for the analyst, `0` = agent finished (orchestrator then runs `git.run_tests`, which defaults to bare `pytest` in the *target* repo; failure → `FAILED`, success → commit + `IN_REVIEW`), anything else = `FAILED`. Do not repurpose 42.

### Initial analysis (Antigravity CLI + superpowers + Gemini 3.8 Flash, streamed)

"Iniciar análise" runs the initial elicitation agent. Task dispatch runs `agy` in one-shot headless mode; the analysis runs **Antigravity CLI (`agy`)** kept alive for a back-and-forth interview, driven by the [superpowers](https://github.com/obra/superpowers) `brainstorming` skill running on Google's **Gemini 3.8 Flash** (`--model gemini-3.8-flash --effort medium`).

Key architectural characteristics:

- **Direct Authentication with the project's key.** `agy` authenticates with the project's Google AI key, passed into the container as `GEMINI_API_KEY`. It does not require complex proxy translation.
- **Input is a file, not a socket.** A bidirectional `docker attach` is not portable (npipe on Windows; multiplexed frame headers without a TTY), so the API *appends* NDJSON to `.painkiller/agent-stdin.jsonl` inside the bind-mounted repo, formatted with `{"event": "user", "type": "user", "message": {"content": ...}}`, and `painkiller agent-run` ([cli/agent_run.py](painkiller/cli/agent_run.py)) polls that file inside the container and feeds the agent's stdin. It only forwards **complete** lines, propagates the agent's exit code, and treats `{"type": "__painkiller_eof__"}` as "close stdin so the agent wraps up". Output comes back the ordinary way, via `container.logs(stream=True, follow=True)`.

The stream-json envelope from `agy` is parsed in `parse_agent_line` into an `AgentEvent`:
- `init`: System event initializing the session with `conversation_id`.
- `step_update`:
  - `step_type: "agent_response"` with `text_delta` -> `ASSISTANT_DELTA`
  - `step_type: "agent_response"` with `thinking_delta` -> `THINKING_DELTA`
  - `step_type: "tool"` with active/running state -> `TOOL_USE`
  - `step_type: "tool"` with done/error state -> `TOOL_RESULT`
- `result`: Turn completed -> `RESULT`, enabling the analyst composer in the UI.

An API restart kills the analysis containers while the restored session still says it is the analyst's turn, so `AnalysisOrchestrator.send` restores the run (`get_or_restore`) and, when the container is not alive, calls `resume` **before** appending the message — `resume` measures the queue offset first, so the new answer is the first thing the restarted agent reads.

`AnalysisOrchestrator` fans events out to SSE subscribers and keeps a replay buffer, so a reconnecting `EventSource` sees the whole conversation. `POST /api/projects/{id}/analysis` returns immediately, streaming events via `/api/analysis/{sid}/stream`.

Sessions and non-transient events are persisted through the tracker, so `get_or_restore` can rebuild a run after a restart. Two things make that replay honest, and both are easy to break:

- **Deltas are never stored** (`TRANSIENT_EVENTS`) — there are thousands per turn. The turn they build up is kept in `AnalysisRun.partial`, which `subscribe` re-emits as one synthetic `ASSISTANT_DELTA` to whoever reconnects mid-turn, and which `_salvage` converts into a canonical `ASSISTANT` when the agent closes a turn without sending one. Without that, an agent whose `step_update` never carries a `response` leaves a blank transcript on reconnect.
- **`container.logs(follow=True)` always starts from the beginning.** So relighting the pump on a container that is still alive replays the entire log. `_rewind` handles it: it empties the in-memory buffer and records how many events are already in the database, and `_pump` skips persisting exactly that many. It is only called when the container survived — a container restarted by `resume` has a fresh log.

The handoff to the backlog is a file: the agent writes the spec to `docs/superpowers/specs/` and the decomposed tasks to `.painkiller/backlogs/{analysis_session_id}.json` (`backlog_relative`), and `POST /api/analysis/{sid}/commit` reads that JSON back off the bind mount. **One file per analysis** — a single project-wide file made every iteration session re-import the previous one's tasks. The legacy `.painkiller/backlog.json` is accepted only if written after the analysis started, and is then moved into that session's path so the next one cannot pick it up.

`docs/` is versioned in Gitea by `AnalysisOrchestrator.sync_docs`: on every persisted `RESULT` (so not on a `_rewind` replay) and again on backlog import, it commits only `docs/` (`GitPort.commit_paths`) on the **currently checked-out** branch and pushes that branch. The push runs even with no new commit, because the brainstorming skill often commits the spec itself. Failures are logged, never raised. Without `git=` in the constructor it does nothing.

So that this lands on the default branch (where the Artefatos links point), `_ensure_default_branch` runs `GitPort.switch_branch` to `project.default_branch` before a new container starts, and before `resume` restarts a dead one — never while a container is alive. It refuses when *tracked* files have uncommitted changes (a failed task's leftovers would otherwise ride along into main); untracked files like `.painkiller/` don't block it. On refusal the analysis just proceeds on the current branch.

### Task dispatch (Antigravity CLI + superpowers + Gemini 3.8 Flash, one-shot)

`dispatch_task` refuses to run a task whose `dependencies` are not all `COMPLETED`, creates/checks out `feature/{task_id}`, builds the Portuguese instruction prompt (including the clarification protocol block and superpowers skill guidelines) in `_build_task_instructions`, then runs `painkiller-worker:latest` with the target repo bind-mounted at `/workspace`. The container executes `agy --model gemini-3.8-flash --effort medium --dangerously-skip-permissions --output-format stream-json --print <instructions>`. Direct authentication uses the project's key, set as `GEMINI_API_KEY`/`GOOGLE_API_KEY` in the container.

Dispatch is synchronous inside the HTTP request (the blocking docker-py wait is offloaded with `run_in_executor`), so `POST /api/tasks/{id}/dispatch` blocks for the full agent run.

While it blocks, progress goes out on a side channel: `DockerSandboxRunner` follows `container.logs(stream=True, follow=True)` (that same read is the final `ExecutionResult.logs`), parses each line with `parse_agent_line` and hands it to the `on_event` callback of `SandboxPort.run_task`. The orchestrator points that callback at its `TaskActivityHub` ([engine/task_activity.py](painkiller/engine/task_activity.py)), adds its own `SYSTEM` notes (container start, exit code, test run), and `GET /api/tasks/{id}/stream` serves it as SSE. The hub is **in-memory only**: its first frame, `STATE`, says `active: false` when this process is not running the task — after a restart the tracker can still say `RUNNING` with nothing behind it, and the UI says so instead of spinning. The container timeout is now a `threading.Timer` that kills the container, since following the log blocks until exit. It is `PAINKILLER_TASK_TIMEOUT` (seconds, default 1800); a kill by the timer comes back as exit 137 with `ExecutionResult.timed_out`. On any failure `Task.error` holds only a short pt-BR message plus `ExecutionResult.summary` (the harness error or the agent's last words, built by the runner with `parse_agent_line`) — never the raw log, which runs to hundreds of KB; the comment carries its last 20 KB. Redispatching a `FAILED` task adds a "continue from what is on the branch" block to the prompt.

**Abreviar testes** (`POST /api/tasks/{id}/abbreviate-tests`, `Task.skip_tests`): the analyst waives the agent's tests and takes on manual testing. The agent is one-shot, so it cannot be told mid-turn: a live run is killed and `dispatch_task` loops (`_dispatch` returns `None` for a restart) with a no-tests prompt on the same branch, so the dispatch request the UI already holds gets the final outcome; `git.run_tests` is skipped. On an orphaned `RUNNING` task (after a restart) it marks it `FAILED` and the UI redispatches. `stop_task` likewise marks an orphaned task `FAILED` itself, since no dispatch is left to do it.

**Branch lifecycle.** A task's `feature/...` branch is pushed before its merge and survives it, because each completed task's "Testar" deploys that branch to Coolify. When a session is finalized (`PainkillerOrchestrator.finalize_session`, called for every open session by `POST /api/projects/{id}/sessions` and by a PATCH to `COMPLETED`), the branches of its `COMPLETED` tasks are deleted locally and on Gitea (`GitPort.delete_branch`, which refuses anything not merged into the default branch). Other tasks keep theirs, since they may be migrated. So "Testar" only exists on the latest open session, and `DeploymentService` answers 409 (`BranchUnavailableError`) for a task of a finalized one.

### DeepSeek harness (`dsh` over ACP)

A project with `harness = deepseek_superpowers` runs the same two flows on `painkiller-agent-deepseek` / `painkiller-worker-deepseek`, and the rest of Painkiller cannot tell the difference. The trick is [cli/acp_run.py](painkiller/cli/acp_run.py) (`painkiller acp-run`): it drives `dsh --profile acp` over the **Agent Client Protocol** (JSON-RPC stdio) and re-emits everything in the **Antigravity stream-json envelope** (`init` / `step_update` / `result`), so `parse_agent_line`, the analysis pump, the task hub and usage accounting are shared.

- **Analysis**: `acp-run --stdin-file … --session-key <claude_session_id>` polls the same NDJSON queue as `agent-run`, one `session/prompt` per analyst line, in **one** ACP session (so the interview has memory). The ACP `sessionId` is stored in `.painkiller/dsh-sessions.json` under the session key; `resume` passes `--resume --stdin-offset <bytes>` and the bridge calls `session/resume`. The offset is measured by the API at restart time — measuring it inside the container would drop a message sent while it booted. `.painkiller/dsh_home/{sessions,storages}` is bind-mounted over `/root/.dsh/…` so the history outlives the container.
- **Tasks**: `acp-run --prompt <instructions>`, one turn then exit — the `agy --print` equivalent. Clarification (exit 42) works unchanged, since `painkiller ask` runs inside the agent's bash tool.
- **Skills**: the images symlink `/opt/superpowers/skills` to `~/.agents/skills`, which `dsh-skill-filesystem` puts in the session catalog; the agent loads them with its `skill` tool.
- **Permissions**: `session/request_permission` is answered with the allow option — the `--dangerously-skip-permissions` equivalent.
- **Tokens**: ACP reports none. The bridge sums `usage` of the `assistant/message` events in the dsh session log (`sessions/*/<id>/session.v3.jsonl.zstd`, multi-frame zstd, decoded through `node` because the image's Python has no zstd) by sequence number, so a late write lands in the next turn instead of being lost. The projection cache (`storages/session_projcache`) lags a turn behind — do not use it.
- **Errors**: `dsh` failures surface as `dsh: <CODE>: <message>` lines; `parse_agent_line` turns `QUOTA`, `AUTH`, `fatal` etc. into `ERROR` events with `raw.harness_error`, the analysis stores the pt-BR text in `session.error`, and the UI shows it as "O agente parou" (weight + hatching, not the accent).
- The project's model and effort reach the bridge as `PAINKILLER_DEEPSEEK_MODEL` / `PAINKILLER_DEEPSEEK_EFFORT` **in the container's environment** (set by the API, never read from its own), and `acp-run` picks the advertised option through `session/set_config_option`; an unknown value keeps dsh's default with a warning.

### Maki harness (`maki`, Claude Code stream-json)

`harness = maki_superpowers` runs on `painkiller-agent-maki` / `painkiller-worker-maki`. The images install the **pinned** release binary (`MAKI_VERSION`), verified against the release's `sha256sums.txt` — never the remote `install.sh`. Maki speaks **Claude Code's stream-json in both directions**, so unlike `dsh` it needs no protocol bridge: the analysis reuses `painkiller agent-run --agent-bin maki` with `--trust --yolo --print --input-format stream-json --output-format stream-json --include-partial-messages`, and `parse_agent_line`'s Claude Code branch does the parsing. Every `result` carries per-turn `usage` **and** `total_cost_usd`.

- **Key and model**: the DeepSeek key (`DEEPSEEK_KEY_HARNESSES`), the project's model (default `deepseek/deepseek-v4-pro`, `provider/model` syntax). No effort setting.
- **Skills**: `/opt/superpowers/skills` is linked to `~/.agents/skills`, which maki scans; the agent loads them with its `Skill` tool.
- **Sessions**: started with `--session-id <claude_session_id>`, resumed with `--session <id>`. Maki stores the session as `sessions/<base58 of the UUID>.jsonl` (`maki_session_file`); `resume` uses `--session` only when that file exists (a container that died before the first turn has nothing to resume). State lives in `.painkiller/maki_home` → `/root/.local/state/maki`, and `sessions/locks` must be pre-created or maki does not save into an empty mount. On a Windows bind mount maki logs `failed to save session …`: that is only `cwd_latest.json` (used by `--continue`, which we never pass); the parser downgrades it to `SYSTEM`.
- **Resume offset**: like `dsh`, `resume` passes `agent-run --stdin-offset <bytes>` so the answered queue is not replayed. (The `agy` path still replays from 0.)
- **Errors, the tricky part**: maki reports a refused key or missing balance as a `result` with `is_error: true` **and exits 0**. Three guards: `parse_agent_line` maps such a result to an `ERROR` with `raw.harness_error` (same UI path as `dsh`); `DockerSandboxRunner._ended_in_error` turns exit 0 into 1 so a failed task never reaches tests/review; and `agent-run --fail-on-error-result` stops the analysis container. In SDK (bidirectional) mode maki does not even emit that result — it waits silently "for re-authentication" and only writes to `~/.local/logs/maki/maki.log` — so `agent-run --agent-log` tails that JSON log and synthesizes the error `result` on 401/402/403.
- Task cost: maki's `result` has no model, so `parse_task_usage` takes it from the `system/init` / `assistant` events of the same log.

### Unreal Agent harness (`unreal-agent-runner`, OpenAI Responses API over DeepSeek)

`harness = unreal_superpowers` runs on `painkiller-agent-unreal` / `painkiller-worker-unreal`, which compile `cmd/unreal-agent-runner` from [unreallabsai/unreal-agent](https://github.com/unreallabsai/unreal-agent) at a **pinned commit** (`UNREAL_AGENT_COMMIT`) with **Go 1.27** — its `go.mod` requires it and the official image sets `GOTOOLCHAIN=local`. The runner's `openai` provider speaks the Responses API, pointed at DeepSeek (`UNREAL_HARNESS_LLM_BASE_URL=https://api.deepseek.com`), which serves `/responses` statelessly — fine, since the runner resends the whole history each call.

The runner executes **one JSON request per process** (`{"messages": [...], "session_id": ...}`, read from stdin; unknown fields are rejected) and prints every persisted session item as JSONL (`{Sequence, Kind, Data}`: `input`, `turn`, `model_response`, `tool_call_status`). The same `session_id` resumes the same history from disk. So, like `dsh`, it goes through a bridge that re-emits the **Antigravity envelope** — [cli/unreal_run.py](painkiller/cli/unreal_run.py) (`painkiller unreal-run`) — and nothing downstream knows about Unreal.

- **Turn end**: the bridge emits `result` when the runner process exits, never on a `message` item (an intermediate message can be followed by more tool calls). The `result` carries the summed `Usage` of the turn's `model_response`s and the model, so `parse_agent_usage`/`parse_task_usage` work unchanged.
- **Analysis**: `unreal-run --stdin-file … --session-id <claude_session_id>` polls the NDJSON queue, one runner process per analyst line. Sessions live in `.painkiller/unreal_home` → `/root/.local/state/unreal-agent`. `resume` passes `--stdin-offset <bytes>` measured by the API, as for `dsh`.
- **Tasks**: `unreal-run --prompt <instructions>`, one turn then exit. Clarification (exit 42) works unchanged via `painkiller ask` in the runner's Bash tool.
- **Skills**: the runner only reads `<workspace>/.harness/skills`, i.e. inside the user's repo. The bridge links (or, where a bind mount refuses symlinks, copies) `/opt/superpowers/skills` there and adds `/.harness/` to `.git/info/exclude`, so `git add -A` never commits it.
- **Errors**: the runner exits 1 and prints `{"type":"error","message":…}`; an LLM failure can also come as `Response.Failure` in a `model_response`. The bridge turns either into a stream-json `result` with `is_error` (so `parse_agent_line` yields an ERROR with `raw.harness_error`, the "O agente parou" path) and exits 1. Runner stderr is relayed as `unreal: …` lines, parsed as `SYSTEM`.
- **Key and model**: the DeepSeek key (`DEEPSEEK_KEY_HARNESSES`) as `UNREAL_HARNESS_LLM_API_KEY`; model via `unreal_model()` — the project's model, else `deepseek-v4-pro`. DeepSeek rejects maki's `provider/` prefix, so a leading `deepseek/` is stripped.
- The runner also loads a `.env` at the workspace root (without overriding variables already set), so a target repo's `.env` reaches the agent's environment.

### Gitea issues (one-way mirror of the backlog)

Every task has a Gitea issue in the project's repo. [gitea_mirror.py](painkiller/adapters/issue_trackers/gitea_mirror.py) is a **decorator over the tracker**, wired in `create_app()` (`GiteaIssueMirror(SQLiteIssueTracker(...), vcs)`): all task writes go through `create_task` / `update_task_status` / `add_comment`, so wrapping them catches every path while `engine/` never learns Gitea exists. Everything else is delegated via `__getattr__`.

- **What the issue shows**: title; body rebuilt on every sync (description, acceptance criteria as a checklist — ticked when `COMPLETED` —, target files, dependencies as `#n`, task id and branch); the status as an **exclusive scoped label** `painkiller/<estado>` (same colour rule as the UI: only `aguardando-analista` is vermilion); closed when `COMPLETED`; the task's comments, with long logs truncated into a `<details>` block.
- **Never on the critical path**: each mirror call runs as a background task, serialized per task id (create before relabel), and failures are logged, never raised. `close()` drains them before disposing the DB — tests call `tracker.close()` directly.
- `Task.issue_number` / `issue_url` (new columns, added by `_migrate_columns`; `set_task_issue` on the port) link the card in the backlog to the issue. Projects without a `repo_url` on this Gitea are skipped.
- **Backfill**: `POST /api/projects/{id}/issues/sync` (button "Sincronizar issues" in the backlog) creates the missing issues and realigns all of them in two passes, so dependencies already resolve to `#n`.
- One-way: closing or editing the issue in Gitea does **not** change the task.

### Usage and cost tracking

Every token spent lands in the `usage_records` table through `UsageLedgerPort`, which `SQLiteIssueTracker` also implements (same database). There are three sources, all optional dependencies (`usage=None` disables recording, which is why older tests need no change):

- **Initial analysis** — `AnalysisOrchestrator._pump` books a record on each `RESULT`, parsed by `parse_agent_usage` in [core/usage.py](painkiller/core/usage.py), which tolerates both the Antigravity and the Claude Code envelopes. It books in the same branch that persists the event, so the `_rewind` skip also keeps a replayed log from being charged twice. The model comes from the `init` event, falling back to the project's model (`harness_model`).
- **Task dispatch** — `parse_task_usage` reads the `stream-json` or `json` events emitted by `agy` in the worker's logs (specifically `usage_metadata` on the final `result` event). It records on every exit code: a failed run still costs money.
- **Direct LLM calls** — `LiteLLMAdapter`; the NVIDIA path requests `stream_options.include_usage` to get counts. `LLMPort.complete`/`structured_output` take an optional `project_id` so the spend is attributed; a call without one is recorded but shows up on no page.

Cost is computed **at read time**, never stored, so changing a price reprices history. The order in `record_cost` is: the analyst's price in `UsageSettings.prices` (matched also without the `provider/` prefix), then the cost the tool reported, then LiteLLM's bundled catalog (`adapters/llm/pricing.py`), then "sem preço" (counted in `unpriced_calls`, excluded from totals). The catalog does not know `gemini-3.8-flash`, so in practice the analyst has to enter that price.

**Everything is per project.** The summary and the records are read at `GET /api/projects/{id}/usage[/records]`, and each project has its own budget (`PUT /api/projects/{id}/usage/budget`, stored in the `settings` table under `usage:budget:{id}` via `get_project_budget`/`save_project_budget`, removed with the project). There is no app-wide summary endpoint. What stays global, at `/api/usage/settings`, is what does not vary by project: model prices, local currency and exchange rate — changing them reprices every project.

"Crédito disponível" is the project's `budget_usd − spent`: Gemini, OpenAI, Anthropic and NVIDIA have no balance API. DeepSeek and OpenRouter do, and `adapters/llm/balance.py` queries them live with the project's own key at `GET /api/projects/{id}/usage/balances` (no UI shows it yet). `app.state.price_lookup` and `app.state.balance_lookup` exist so tests can swap the catalog and the network out.

The token counts come from the agents' own output formats, which are not a stable contract: if a new `agy` version changes them, recording stops silently (nothing breaks, the page just stops growing). The tests in `test_usage.py` pin the formats that are expected.

## Frontend

SvelteKit 2 + Svelte 5 (runes), TypeScript, plain CSS. No Tailwind, no component library, no Framer Motion — the design system is `web/src/app.css` (tokens) plus scoped `<style>` blocks.

Served as a pure SPA: `web/src/routes/+layout.ts` sets `ssr = false`, `adapter-static` emits a `fallback: 'index.html'`, and `create_app()` registers a catch-all **after** the routers that returns a real file when one exists on disk and `index.html` otherwise. That catch-all explicitly 404s anything under `api/` so an unknown endpoint stays JSON instead of silently becoming the SPA shell.

Design rules that are load-bearing, not decoration:

- **Exactly one colour exists.** The whole UI is ink on paper; the vermilion `--accent` is reserved for a single meaning — an agent is blocked waiting for the analyst (`AWAITING_ANALYST`, i.e. exit 42). Task statuses are otherwise distinguished by weight, marker and diagonal hatching (`FAILED`), never by a status-colour palette. Spending the accent anywhere else breaks the signal.
- Zero border-radius, hairline `1px` rules instead of cards, `Geist` + `Geist Mono`, no emoji (icons are inline SVG in `Icon.svelte`), skeletons instead of spinners.

**Terminology:** the UI calls this step *"análise inicial"* and routes it at `/projects/[id]/initial-analysis`, and the backend agrees (`/api/analysis/*`). The project tabs are numbered because the first three are a path, not a menu: `1 Contexto → 2 Análise inicial → 3 Backlog`, with `Artefatos` and `Custos` set apart as reference views. That tab (`/projects/[id]/artifacts`) is the single home for everything the agent wrote — superpowers specs and plans, the backlogs in `.painkiller/backlogs/`, and the per-file Gitea links — which used to be scattered across a sidebar panel inside the analysis and a link in the project subtitle. The older `/api/interrogation/*` endpoints and their `api.ts` wrappers are still there but unused by the UI. UI copy is pt-BR.

**Long-running requests:** `POST /api/tasks/{id}/dispatch` and `POST /api/tasks/{id}/clarification` hold the HTTP connection open for the entire container run. The UI has no timeout; for dispatch, `TaskActivity.svelte` subscribes to `/api/tasks/{id}/stream` and shows the tool calls and text the agent produces, plus "última atividade há N s" — deltas count as activity, and after two minutes of silence it warns that the agent may be stuck (weight and hatching, not the accent). The análise-inicial page is the exception: it streams, so the clock there only covers the gap between turns, and `TOOL_USE` events are deliberately **not** shown in the transcript (the audience is not developers) — they only trigger a refresh of the artifacts, while a generic "Trabalhando." indicator covers the silence.

**The analysis session lives in a module, not in the route component** ([stores/analysis.svelte.ts](web/src/lib/stores/analysis.svelte.ts), keyed by project id). The page is a thin view over it: leaving for the backlog tab and coming back no longer closes the `EventSource` nor rebuilds the transcript, and `ensureBooted()` makes the second visit a no-op instead of a second container. Only `signOut` disposes it. The store still stashes the session id in `sessionStorage`/`localStorage` so a hard reload re-attaches, and still reports a 404 from `/analysis/{id}/message` as a dead session. A **watchdog** in the store covers a frame lost in transit: when the UI shows "agente trabalhando", the stream has been silent for 20 s and `GET /analysis/{id}` says `WAITING_ANALYST`/`FINISHED`/`FAILED`, it wipes the transcript and re-attaches, so the replay rebuilds the right state — exactly what an F5 did. Without it the Choices form stayed disabled with the agent already stopped.

**Clickable choices.** `build_analysis_prompt` tells the agent to end a multiple-choice question with a fenced ```` ```painkiller-choices ```` JSON block (`{"multiple": bool, "options": [{"label", "description"}]}`). [lib/choices.ts](web/src/lib/choices.ts) strips it from the markdown and `Choices.svelte` renders it as options plus a free-text field; the answer goes through the same `send()` as the composer, so the backend is unaware of it. The fence name is duplicated in `CHOICES_FENCE` (analysis.py) and `choices.ts`. A missing or malformed block just falls back to plain markdown.

The analysis page sizes itself to the viewport (measured, because the project header height varies) and scrolls **inside** the transcript, so the composer stays anchored and the document itself does not scroll. Auto-scroll only follows the stream while the reader is already at the bottom. Session actions live in a sticky toolbar where exactly one button is solid — `Importar backlog`, the action that ends the step; `Recomeçar do zero` is demoted into the `···` menu.

`/projects/[id]/costs` is the usage page, scoped to that project (there is no global one): credit left, spend in USD and local currency (via a manually entered exchange rate), tokens, per-day chart and breakdowns by step/model, plus a form that saves the project's budget and the shared price list in one go. Going over budget is shown by weight and hatching, **not** by the accent — that colour stays reserved for exit 42.

`/pending` sweeps every project and lists its tasks client-side (N+1) because the API has no global pending-clarifications endpoint. That is the natural place for a backend addition.

## Container topology

`docker-compose.yml` runs the API in a container that creates the agent containers as **siblings** over the mounted host socket, never nested. That one fact drives everything else here.

**The bind-mount source is resolved by the host daemon, not by the API container.** So when `DockerSandboxRunner` passes `repo_path` as the worker's `/workspace` source, a container-local path like `/app/storage/projects/X/repo` means nothing on the other side. `_daemon_path()` rewrites the prefix using `PAINKILLER_CONTAINER_ROOT` (fixed by compose) and the host root installed with `paths.set_host_root` (covered by `tests/unit/test_sandbox_paths.py`). With either unset it returns the plain absolute path, so running on the host directly is unaffected — that is the default.

The host path of `./storage` is **detected**: at startup `PlatformConfig.load` calls `paths.detect_host_root`, which looks the API up by its hostname (Docker's short container id — do not set `hostname:` on the `api` service) and reads the `Source` of the bind mounted at `PAINKILLER_CONTAINER_ROOT`. Precedence: saved in the wizard → detected; `PAINKILLER_HOST_ROOT` is no longer read. Get it wrong and the UI still works end to end; only dispatch silently mounts the wrong directory into the agent — which is what the wizard's "Testar montagem" (`POST /api/setup/environment/test`, a throwaway container that reads a sentinel through `daemon_path`) catches.

`./storage` must stay a bind mount rather than a named volume, precisely because the sibling containers address it through the host.

The `coolify` network is `external: true` on purpose: Coolify creates it itself (without compose labels) whenever it is missing, so a compose-managed declaration fails with `network coolify was found but has incorrect label com.docker.compose.network`. Do not make it compose-managed again; it only has to exist before `up`.

Coolify's "localhost" server (id 0) is the `coolify-host` SSH bridge, and three pieces make that work on any fresh machine — without them onboarding dies with `getPublicKey() on null`, because the seeder creates server 0 pointing at a private key it never found:
- `coolify-ssh-init` (one-shot) generates the key per machine into the `coolify-ssh` volume as `keys/id.root@host.docker.internal`, the name Coolify's `ProductionSeeder` imports on every boot. Coolify then renames it to `ssh_key@<uuid>`, so `authorized_keys` in the volume is the source of truth: when it exists nothing is regenerated (a new key would no longer match the one in Coolify's database). No key is committed.
- The volume is mounted at Coolify's `storage/app/ssh` and read-only into `coolify-host`, which installs `authorized_keys` at start.
- On the private `coolify-ssh` network, `coolify-host` carries the alias `host.docker.internal` — the IP the seeder hardcodes, which on Docker Desktop is otherwise the Windows host, with no sshd. Only Coolify is on that network, so no other container's `host.docker.internal` changes.

Other pieces: `docker/api.Dockerfile` is multi-stage (Node builds `web/`, then a Python runtime with no Node), so the image does not depend on the committed `painkiller/api/static/`. `PAINKILLER_DB_URL` puts SQLite on a named volume. The `worker-image` service exists only so compose builds the image the API instantiates by name; it sits behind a `build` profile so `up` never starts it.

### Packaging note

`[tool.setuptools.packages.find] include = ["painkiller*"]` in `pyproject.toml` is required: without it, flat-layout auto-discovery sweeps `web/node_modules/` into the distribution (147 phantom packages). `.dockerignore` keeps the same tree out of the worker image's build context, which `worker.Dockerfile` populates with `COPY . /tmp/painkiller`.

### Setup wizard and platform settings

**First access.** A fresh database has no administrator: `/api/auth/config` answers `first_access: true`, `/login` forwards to `/first-access`, and `POST /api/auth/first-access` (public, refused with 409 once an admin exists, serialized by a lock in `PlatformConfig.create_admin`) stores the username and a **scrypt** hash in `PlatformSettings` and returns a session. Whoever reaches a fresh install first owns it — the scripts tell the operator to open it right away. The account is edited in **Admin → Configurações** (`PUT /api/setup/admin`, current password required; a new password changes the token fingerprint, so older admin sessions die and the response carries a fresh token). Forgotten password: `painkiller admin-reset` (`cli/admin_reset.py`) clears it in the database, then restart the API.

The admin's next stop is redirected (by `+layout.svelte`, through `stores/setup.svelte.ts`) to `/setup`; the same step components, plus the admin account form, live on at `/admin/settings`. Backend: [routes/setup.py](painkiller/api/routes/setup.py) (`/api/setup/*`, `require_admin`) over [api/platform.py](painkiller/api/platform.py).

- **`PlatformSettings`** (domain) is stored in the `settings` table under `platform` through `PlatformSettingsPort`, implemented by `SQLiteIssueTracker`. The installation's random key (`get_secret_key`, row `platform:secret-key`, created on first boot) both signs session tokens (installed with `security.set_auth_secret` by `PlatformConfig.load`) and seals the secret fields (`google_client_secret`, `coolify_api_token`, `coolify_root_password`) with Fernet (`secret_box.py`). It sits in the same database, so sealing only protects against leaking the settings row alone, not a copy of the whole file. Losing that row logs everyone out and makes the sealed fields unreadable (treated as empty).
- **Database only**: `PlatformConfig` resolves each value as saved setting → detected/observed value → code default, never the environment. `apply()` pushes them into the live adapters and modules (`security.set_admin_account`, `paths.set_host_root`, `GoogleOAuthClient.configure`, `CoolifyAdapter.configure`), reading adapters from `app.state` so tests that swap `google_oauth`/`deployment` still work. Saving applies immediately, without a restart; emptying a field disables it.
- **URLs**: without a saved or env `PAINKILLER_PUBLIC_URL`, `observe()` adopts the URL the admin opened the wizard with, so the Google redirect URIs and the Coolify link agree with it.
- **Coolify automation** ([coolify_bootstrap.py](painkiller/adapters/deployment/coolify_bootstrap.py)): Coolify has no API to mint the first token, so `docker exec painkiller-coolify php artisan tinker` (as `www-data`) runs PHP in one DB transaction: create root user id 0 in team 0 if missing (Coolify's `User` created-event may already attach the team — guard it), enable `instanceSettings()->is_api_enabled`, delete the previous `painkiller` token and insert a Sanctum token with `abilities: ["root"]` and `team_id: 0`. Credentials go in via exec env vars, never interpolated into PHP. The result is the `PAINKILLER_JSON:` line. It depends on Coolify internals (checked on 4.3.23); if an upgrade breaks it, the error surfaces and the manual path (links to `/register`, `/settings/advanced`, `/security/api-tokens`) still works. The automation does **not** create the deploy server: Coolify's `ProductionSeeder` registers this host as server 0 (`localhost`, via the `coolify-host` SSH bridge — see **Container topology**), the `coolify` destination network and starts the Traefik proxy on every boot. `CoolifyAdapter.check` reports each server's `usable` (`is_reachable && is_usable`), shown as the "Servidor de deploy" line of the checklist; with exactly one server its uuid is adopted automatically.
- The admin account and the signing key are **module state** in `security.py`, installed from the database at startup. Tests freeze both in `tests/conftest.py` (`frozen_admin` turns the setters into no-ops so every fresh test database keeps the admin `admin_headers()` signs for); `tests/unit/test_first_access.py` overrides that fixture to exercise the real flow.
- **Gitea service account**: `PlatformConfig.load` generates `gitea_password` on first boot (sealed like the other secrets) and `apply()` installs it in `GiteaAdapter` and the push credentials of `GitCliAdapter` (`set_http_credentials`); `ensure_admin_user` then creates the account or realigns an existing one to it. The Gitea URL is always `public URL + /gitea`: `apply()` pushes it into `GiteaAdapter.external_base_url` and Coolify, and `sync_gitea_root_url` writes Gitea's own `ROOT_URL` with the image's `environment-to-ini` and restarts the container, only when it changed (on startup, once Gitea answers, and when the public URL is saved). That is why compose no longer sets `GITEA__server__ROOT_URL`: the entrypoint would rewrite `app.ini` on every start.
- **Session lifetime**: `session_ttl_hours` (default 12, 1–720), in the Ambiente step, installed with `security.set_session_ttl`.

### Auth

Every router except `/api/auth` is mounted with `Depends(current_user)` in `create_app()`; tokens and authorization live in [api/security.py](painkiller/api/security.py). Tokens are HMAC-signed with the installation's secret key from the database, so sessions survive restarts. `EventSource` and download links cannot send headers, so the backend also accepts `?token=` — the UI builds those URLs with `authedUrl()` in `api.ts`.

Two kinds of user:

- **Administrator** (`BREAK_GLASS_ID`) — created on the first access, stored in `PlatformSettings` (username + scrypt hash), sees every project and remains the emergency login when Google is down. Its tokens carry a fingerprint of the stored hash, so changing the password revokes them.
- **Google users** — configured in the setup wizard. [routes/auth.py](painkiller/api/routes/auth.py) runs the OAuth Authorization Code flow server-side (`/api/auth/google/login` → Google → `/callback`, `state` signed and bound to a cookie) and hands the token back in the **fragment** of `/login#token=…`. First sign-in creates the `User` (`UserDirectoryPort`, implemented by `SQLiteIssueTracker`, `users` table). The allowed domains (`GoogleOAuthClient.allowed_domain_set`) optionally restrict sign-up. Changing the client secret later realigns Gitea's OAuth source with `gitea admin auth update-oauth`. The client is `app.state.google_oauth` so tests swap it out.

**Every user is bound to their own Gitea account** (`User.gitea_username`), created by `ensure_gitea_account` through the Gitea admin API with a random password. A project stores `owner_id`, and its repo is created **private** under that account via `POST /admin/users/{owner}/repos`; the service account (a site admin) still does the pushing. A taken name gets a `-2`, `-3`… suffix instead of reusing the other project's repo, slugs are forced to ASCII (Gitea rejects `ã`), and deleting a project **archives** its Gitea repo.

**The service-account password must never land in a repo.** Repos are bind-mounted into the agent containers, so the `origin` URL is stored without credentials; `GitCliAdapter(http_credentials=vcs.push_credentials())` injects them per push through `GIT_CONFIG_*` env vars (`http.extraHeader`), and startup plus every push scrub `user:pass@` from remotes written by older versions. The password is generated by the API and kept sealed in the database; `ensure_admin_user` realigns Gitea to it on every start. When Google is configured the API also registers a `google` OAuth source in Gitea (via `docker exec`, `gitea admin auth add-oauth`) and links the account by the Google `sub`, so the user signs in to Gitea with the same Google account and sees only their repos. Compose adds `FORCE_PRIVATE` and private user visibility on top.

Isolation in the API: `list_projects` filters by owner; `require_project` / `require_task` / `require_analysis` answer **404** (not 403) for anything that belongs to someone else. Projects with no `owner_id` (legacy, or created by the admin) are admin-only. Only the admin may pass `repo_path` on project creation. The price list at `/api/usage/settings` is still shared by everyone signed in.
