# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Painkiller is a platform that lets a **non-technical person** describe the software they need and get it built and **published to production**. The person is interviewed by a containerized Antigravity CLI agent running the superpowers `brainstorming` skill, the resulting spec is decomposed into atomic tasks, each task is dispatched to a sandboxed Aider agent on a feature branch, passing tasks are merged, and the default branch is deployed through **Coolify**. See **Autopilot and publishing**.

**Two different agents.** The interview runs Antigravity CLI (`agy`), kept alive and streamed; the coding runs Aider, one-shot. See **Initial analysis** and **Task dispatch**.

The target user is a layperson: UI copy and the analysis prompt avoid jargon, and the platform is expected to make technical decisions itself. The manual per-task controls (dispatch, approve, merge) still exist for analysts, but the primary path is the autopilot.

Code comments, LLM prompts, API error messages and the UI are in **Portuguese (pt-BR)**; code identifiers and docstrings are in English. Follow that split.

## Commands

```bash
pip install -e ".[dev]"           # install package + test deps
pytest                             # full suite (108 tests, no Docker/Coolify needed — both are mocked)
pytest tests/unit/test_orchestrator.py::test_dispatch_task_success   # single test
uvicorn painkiller.api.server:app --reload    # API + built UI at http://localhost:8000/
docker build -f docker/worker.Dockerfile -t painkiller-worker:latest .   # worker image (required before dispatching tasks)
docker build -f docker/agent.Dockerfile -t painkiller-agent:latest .     # analysis agent image (required before "Iniciar análise")
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
docker compose --profile build build    # api image + painkiller-worker + painkiller-agent
docker compose up -d                    # api on :8000; the *-image services never start
docker compose logs -f api
docker compose down
```

`pyproject.toml` sets `asyncio_mode = "auto"` and `pythonpath = ["."]`, so async tests need no event-loop boilerplate and the package is importable without install. `tests/`, `tests/unit/` and `tests/integration/` are packages (`__init__.py`) because `test_git_adapter.py` exists in both unit and integration; without them pytest refuses to collect the duplicate basename.

There is no linter or formatter configured.

## Configuration

`.env` is loaded with `override=True` at import time in [server.py](painkiller/api/server.py) — before FastAPI imports — so env changes require a server restart, and `.env` wins over the shell environment.

LLM selection resolves through [litellm_adapter.py](painkiller/adapters/llm/litellm_adapter.py) in this order: `PAINKILLER_LLM_MODEL` / `PAINKILLER_LLM_API_BASE` / `PAINKILLER_LLM_API_KEY`, then provider-specific vars (`NVIDIA_API_KEY`, `OPENAI_API_BASE`, `OPENAI_API_KEY`). When the key starts with `nvapi-` or the base URL contains `nvidia.com`, the adapter bypasses LiteLLM entirely and streams SSE against NVIDIA Build NIM via httpx (`_complete_nvidia`) — that path exists because reasoning models there need streaming and long timeouts. Default model is `moonshotai/kimi-k3`.

`pypdf` and `python-docx` are optional — [attachment_reader.py](painkiller/core/attachment_reader.py) degrades gracefully without them. `.env.example` lists every variable the platform reads.

Coolify is configured with `COOLIFY_URL`, `COOLIFY_TOKEN`, `COOLIFY_PROJECT_UUID`, `COOLIFY_SERVER_UUID` (all four required), plus optional `COOLIFY_ENVIRONMENT_NAME`, `COOLIFY_DOMAIN_TEMPLATE` (`{slug}`/`{id}` placeholders) and `COOLIFY_GIT_BASE_URL` (how the Coolify server reaches the embedded Gitea when that differs from `PAINKILLER_GITEA_EXTERNAL_URL`). With any of the four missing, `CoolifyAdapter.is_configured()` is false: the deploy routes answer 503 and the autopilot skips publishing instead of failing.

## Architecture

Hexagonal / ports & adapters. The dependency rule is strict: `core/` and `engine/` import only from `core/`; adapters implement the ABCs in [core/ports/](painkiller/core/ports/); wiring happens only in `create_app()`.

- **[core/domain/models.py](painkiller/core/domain/models.py)** — Pydantic entities (`Project`, `Task`, `ClarificationRequest`, `ExecutionResult`) plus the `TaskStatus` lifecycle: `BACKLOG → READY → RUNNING → {AWAITING_ANALYST | IN_REVIEW | FAILED} → COMPLETED`.
- **[core/ports/](painkiller/core/ports/)** — six ABCs: `IssueTrackerPort`, `SandboxPort`, `AgentSessionPort`, `GitPort`, `LLMPort`, `DeploymentPort`. Adding a method here means updating the adapter *and* the `AsyncMock`-based unit tests.
- **[adapters/](painkiller/adapters/)** — `sqlite_tracker` (async SQLAlchemy; list fields are stored as JSON text columns and `Project.deployment` as a JSON text column, converted in `_to_task_domain`/`_to_project_domain`; `init_db` adds missing columns to legacy databases), `git_adapter` (shells out to `git`), `docker_runner` (docker-py, one-shot), `docker_agent_session` (docker-py, long-lived), `vcs/gitea_adapter` (embedded Gitea, not behind a port), `deploy/coolify_adapter` (Coolify REST v1 over httpx), `litellm_adapter`. The container-to-host path rewrite both docker adapters need lives in `sandbox/paths.py`.
- **[engine/orchestrator.py](painkiller/engine/orchestrator.py)** — the state machine. Everything below hangs off it. **[engine/verification.py](painkiller/engine/verification.py)** decides how a task is verified; **[engine/autopilot.py](painkiller/engine/autopilot.py)** runs the whole backlog.
- **[engine/analysis.py](painkiller/engine/analysis.py)** — the interactive initial analysis (see **Initial analysis** below). Also an in-process session dict.
- **[interrogation/wizard.py](painkiller/interrogation/wizard.py)** — the *older* LLM interview + backlog generation, still wired at `/api/interrogation/*` but no longer reachable from the UI. **Sessions live in an in-process dict**, so they are lost on restart and will not survive multiple workers.
- **[api/](painkiller/api/)** — FastAPI. Adapters are instantiated in `create_app()` and reached from handlers via `request.app.state.<name>`; tests override by passing a temp `db_url` to `create_app()`.
- **[api/static/](painkiller/api/static/)** — **generated**, never hand-edited. It is the SvelteKit build output, committed so that a clone can run `uvicorn` with no Node toolchain. The source is `web/`.

### Clean-interruption protocol (exit code 42)

The distinguishing mechanism of this codebase. When the agent in the container hits ambiguity, its prompt tells it to run `painkiller ask "<question>" --context "<where>"` instead of guessing. That CLI ([cli/ask.py](painkiller/cli/ask.py)) writes `.painkiller/clarification.json` into the workspace, `git add -A && git commit` the WIP, and exits **42**.

`DockerSandboxRunner` sees exit 42, reads that JSON back off the bind-mounted repo path, and returns it as `ExecutionResult.clarification`. The orchestrator then records the clarification, sets the task to `AWAITING_ANALYST`, and stops. `POST /api/tasks/{id}/clarification` resolves it and re-enters `dispatch_task` from the top — the task re-runs on the same branch with the WIP commit already in place.

So exit codes carry meaning end to end: `42` = paused for the analyst, `0` = agent finished (orchestrator then verifies; failure → `FAILED`, success → commit + `IN_REVIEW`), anything else = `FAILED`. Do not repurpose 42.

**Answers must reach the agent.** `_build_task_instructions` appends every *answered* clarification of the task (`tracker.list_clarifications`) as a "já respondido, não pergunte de novo" block. Without it the re-run asks the same question again. `DockerSandboxRunner` deletes `.painkiller/clarification.json` after reading it so a stale file is never mistaken for a new question.

**Verification is detected, not hardcoded.** `Project.test_command` wins when set; otherwise `verification.detect_test_command` looks at the target repo (`package.json` test script, pytest markers, `go.mod`, `Cargo.toml`). No command → the step is skipped and the task goes to `IN_REVIEW` with a note. pytest exit 5 ("no tests collected") counts as a pass. The command runs on the API host/container, not inside the worker, so the API image needs the runtime (it ships `pytest`; `npm test` needs Node, which the API image does not have — set `test_command` or accept the skip).

**`.painkiller/` is platform state inside the target repo** (agent stdin queue, Antigravity home, `backlog.json`, `clarification.json`). `GitCliAdapter.ensure_ignored` puts it in the repo's `.gitignore` at init so neither the analysis agent nor `painkiller ask`'s `git add -A` commits it.

### Initial analysis (Antigravity CLI + superpowers + Gemini 3.8 Flash, streamed)

"Iniciar análise" runs a **different agent from the one that writes code**. Task dispatch runs Aider one-shot; the analysis runs **Antigravity CLI (`agy`)** kept alive for a back-and-forth interview, driven by the [superpowers](https://github.com/obra/superpowers) `brainstorming` skill running on Google's **Gemini 3.8 Flash** (`--model gemini-3.8-flash --effort medium`).

Key architectural characteristics:

- **Direct Authentication with `GEMINI_API_KEY`.** `agy` authenticates directly using the Google AI API key defined in `.env` (`GEMINI_API_KEY` or fallback `GOOGLE_API_KEY`). It does not require complex proxy translation.
- **Input is a file, not a socket.** A bidirectional `docker attach` is not portable (npipe on Windows; multiplexed frame headers without a TTY), so the API *appends* NDJSON to `.painkiller/agent-stdin.jsonl` inside the bind-mounted repo, formatted with `{"event": "user", "type": "user", "message": {"content": ...}}`, and `painkiller agent-run` ([cli/agent_run.py](painkiller/cli/agent_run.py)) polls that file inside the container and feeds the agent's stdin. It only forwards **complete** lines, propagates the agent's exit code, and treats `{"type": "__painkiller_eof__"}` as "close stdin so the agent wraps up". Output comes back the ordinary way, via `container.logs(stream=True, follow=True)`.

The stream-json envelope from `agy` is parsed in `parse_agent_line` into an `AgentEvent`:
- `init`: System event initializing the session with `conversation_id`.
- `step_update`:
  - `step_type: "agent_response"` with `text_delta` -> `ASSISTANT_DELTA`
  - `step_type: "agent_response"` with `thinking_delta` -> `THINKING_DELTA`
  - `step_type: "tool"` with active/running state -> `TOOL_USE`
  - `step_type: "tool"` with done/error state -> `TOOL_RESULT`
- `result`: Turn completed -> `RESULT`, enabling the analyst composer in the UI.

`AnalysisOrchestrator` fans events out to SSE subscribers and keeps a replay buffer, so a reconnecting `EventSource` sees the whole conversation. `POST /api/projects/{id}/analysis` returns immediately, streaming events via `/api/analysis/{sid}/stream`.

The handoff to the backlog is a file: the agent writes the spec to `docs/superpowers/specs/` and the decomposed tasks to `.painkiller/backlog.json`, and `POST /api/analysis/{sid}/commit` reads that JSON back off the bind mount.

### Task dispatch

`dispatch_task` refuses to run a task whose `dependencies` are not all `COMPLETED`, creates/checks out `feature/{task_id}`, builds the Portuguese instruction prompt (including the clarification protocol block) in `_build_task_instructions`, then runs `painkiller-worker:latest` with the target repo bind-mounted at `/workspace`. API keys are copied from the server's environment into the container, and NVIDIA/custom-base vars are remapped onto `OPENAI_API_KEY`/`OPENAI_API_BASE` because that is what Aider reads.

Dispatch is synchronous inside the HTTP request (the blocking docker-py wait is offloaded with `run_in_executor`), so `POST /api/tasks/{id}/dispatch` blocks for the full agent run.

Aider only reads `OPENAI_API_KEY`/`OPENAI_API_BASE` for OpenAI-compatible endpoints. `docker_runner.resolve_aider_model` maps the Painkiller/NVIDIA variables onto those, defaults the base URL to NVIDIA Build for `nvapi-` keys, and prefixes a bare model name with `openai/` whenever a custom base is set — otherwise LiteLLM treats `moonshotai/kimi-k3` as an unknown provider.

### Autopilot and publishing

`ProjectAutopilot` ([engine/autopilot.py](painkiller/engine/autopilot.py)) is the layperson's path: `POST /api/projects/{id}/run` starts one background `asyncio.Task` per project that loops `pick_next` (first `BACKLOG`/`READY` task in creation order whose dependencies are all `COMPLETED`) → `dispatch_task` → on `IN_REVIEW` `merge_task` → repeat. It stops and hands control back on `AWAITING_ANALYST` (state `PAUSED`) or `FAILED`; calling `run` again resumes because the truth lives in task statuses, not in the run object. When nothing is left it calls `publish_project` if the deployer is configured. `GET /api/projects/{id}/run` returns the `AutopilotRun`; like analysis sessions it is in-process and lost on restart (the tasks keep their statuses).

Publishing: `PainkillerOrchestrator.publish_project` pushes the default branch, `deployer.ensure_application(project)` creates the Coolify application from `project.repo_url` (Gitea) + `project.deployment` (port/build pack, which the analysis agent writes into `backlog.json`'s `deploy` block and `commit_backlog` persists), then `deployer.deploy`. The result is stored back in `Project.deployment`. `merge_task` redeploys automatically when an application already exists. Routes: `GET /api/projects/{id}/deployment` (refreshes status from Coolify when a deploy is in flight) and `POST /api/projects/{id}/deploy`.

The Coolify server must be able to clone from Gitea, so the Gitea repo is created public and `COOLIFY_GIT_BASE_URL` rewrites the host when needed. The analysis prompt asks the first backlog task to produce a root `Dockerfile` listening on `0.0.0.0:<deploy.port>` with `GET /health`, because that is what makes the `dockerfile` build pack deploy without human help.

## Frontend

SvelteKit 2 + Svelte 5 (runes), TypeScript, plain CSS. No Tailwind, no component library, no Framer Motion — the design system is `web/src/app.css` (tokens) plus scoped `<style>` blocks.

Served as a pure SPA: `web/src/routes/+layout.ts` sets `ssr = false`, `adapter-static` emits a `fallback: 'index.html'`, and `create_app()` registers a catch-all **after** the routers that returns a real file when one exists on disk and `index.html` otherwise. That catch-all explicitly 404s anything under `api/` so an unknown endpoint stays JSON instead of silently becoming the SPA shell.

Design rules that are load-bearing, not decoration:

- **Exactly one colour exists.** The whole UI is ink on paper; the vermilion `--accent` is reserved for a single meaning — an agent is blocked waiting for the analyst (`AWAITING_ANALYST`, i.e. exit 42). Task statuses are otherwise distinguished by weight, marker and diagonal hatching (`FAILED`), never by a status-colour palette. Spending the accent anywhere else breaks the signal.
- Zero border-radius, hairline `1px` rules instead of cards, `Geist` + `Geist Mono`, no emoji (icons are inline SVG in `Icon.svelte`), skeletons instead of spinners.

**Terminology:** the UI calls this step *"análise inicial"* and routes it at `/projetos/[id]/analise-inicial`, and the backend now agrees (`/api/analysis/*`). The older `/api/interrogation/*` endpoints and their `api.ts` wrappers are still there but unused by the UI. UI copy is pt-BR.

**New surfaces:** `PublishPanel.svelte` (project page aside) shows deployment status/URL and the "Publicar" button, polling every 6s while a deploy is in flight; `AutopilotBar.svelte` (top of the backlog) starts the autopilot and polls `GET /run` every 4s while active, disabling the manual dispatch/merge buttons meanwhile. Neither uses the accent colour: a paused autopilot surfaces through the task's `AWAITING_ANALYST` tag, which is the one place the accent already lives.

`openAnalysisStream` must list `USER` among the SSE event types it subscribes to: the replay buffer carries the analyst's own turns, and without that listener a reconnect shows only the agent's side.

**Long-running requests:** `POST /api/tasks/{id}/dispatch` and `POST /api/tasks/{id}/clarification` hold the HTTP connection open for the entire container run. The UI has no timeout and shows an elapsed clock (`Elapsed.svelte`) because that is the only honest progress signal available. The análise-inicial page is the exception: it streams, so the clock there only covers the gap between turns, and `TOOL_USE` events give real progress while the agent works in silence.

**Analysis sessions are in-process** (a dict on `AnalysisOrchestrator`), so a uvicorn restart invalidates them, orphans the container and makes `/analysis/{id}/message` return 404. The page detects that 404 specifically and says so. It also stashes the session id in `sessionStorage` so a page reload re-attaches to the running session instead of starting a second container — the SSE replay buffer means re-attaching loses no conversation.

`/pendencias` sweeps every project and lists its tasks client-side (N+1) because the API has no global pending-clarifications endpoint. That is the natural place for a backend addition.

## Container topology

`docker-compose.yml` runs the API in a container that creates the agent containers as **siblings** over the mounted host socket, never nested. That one fact drives everything else here.

**The bind-mount source is resolved by the host daemon, not by the API container.** So when `DockerSandboxRunner` passes `repo_path` as the worker's `/workspace` source, a container-local path like `/app/storage/projects/X/repo` means nothing on the other side. `_daemon_path()` rewrites the prefix using the `PAINKILLER_CONTAINER_ROOT` / `PAINKILLER_HOST_ROOT` pair (covered by `tests/unit/test_sandbox_paths.py`). With either variable unset it returns the plain absolute path, so running on the host directly is unaffected — that is the default.

`PAINKILLER_HOST_ROOT` must be the **absolute host path** of `./storage` and lives in `.env`. Get it wrong and the UI still works end to end; only dispatch silently mounts the wrong directory into the agent.

`./storage` must stay a bind mount rather than a named volume, precisely because the sibling containers address it through the host.

Other pieces: `docker/api.Dockerfile` is multi-stage (Node builds `web/`, then a Python runtime with no Node), so the image does not depend on the committed `painkiller/api/static/`. `PAINKILLER_DB_URL` puts SQLite on a named volume. The `worker-image` service exists only so compose builds the image the API instantiates by name; it sits behind a `build` profile so `up` never starts it.

### Packaging note

`[tool.setuptools.packages.find] include = ["painkiller*"]` in `pyproject.toml` is required: without it, flat-layout auto-discovery sweeps `web/node_modules/` into the distribution (147 phantom packages). `.dockerignore` keeps the same tree out of the worker image's build context, which `worker.Dockerfile` populates with `COPY . /tmp/painkiller`.

### Auth

[api/routes/auth.py](painkiller/api/routes/auth.py) is a hardcoded single-user stub (`admin`/`123456`, fixed token) and no route enforces it. Treat it as a placeholder, not a security boundary.
