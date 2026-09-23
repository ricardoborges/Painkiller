"""Tests for the live activity of task dispatches (hub, runner callback, SSE)."""

import json
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from painkiller.adapters.sandbox.docker_runner import DockerSandboxRunner
from painkiller.api.server import create_app
from tests.auth_helpers import admin_headers
from painkiller.core.domain.models import (
    AgentEvent,
    AgentEventType,
    ExecutionResult,
    Project,
    Task,
)
from painkiller.engine.orchestrator import PainkillerOrchestrator
from painkiller.engine.task_activity import TaskActivityHub


def _event(kind: AgentEventType, text: str = "") -> AgentEvent:
    return AgentEvent(type=kind, text=text)


async def test_hub_replays_buffer_without_deltas_but_with_partial():
    hub = TaskActivityHub()
    hub.start("t1")
    hub.publish("t1", _event(AgentEventType.TOOL_USE, "run_command"))
    hub.publish("t1", _event(AgentEventType.ASSISTANT_DELTA, "Crian"))
    hub.publish("t1", _event(AgentEventType.ASSISTANT_DELTA, "do o arquivo"))
    hub.finish("t1")

    seen = [(e.type, e.text) async for e in hub.subscribe("t1")]

    assert seen == [(AgentEventType.TOOL_USE, "run_command")]  # parcial some ao terminar


async def test_hub_follows_live_until_finish():
    hub = TaskActivityHub()
    hub.start("t1")
    hub.publish("t1", _event(AgentEventType.SYSTEM, "início"))
    hub.publish("t1", _event(AgentEventType.ASSISTANT_DELTA, "meio"))

    stream = hub.subscribe("t1")
    assert (await anext(stream)).text == "início"
    replayed_partial = await anext(stream)
    assert replayed_partial.type == AgentEventType.ASSISTANT_DELTA
    assert replayed_partial.text == "meio"

    hub.publish("t1", _event(AgentEventType.TOOL_USE, "write_file"))
    assert (await anext(stream)).text == "write_file"
    hub.finish("t1")
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


async def test_unknown_task_yields_nothing():
    hub = TaskActivityHub()
    assert [e async for e in hub.subscribe("nope")] == []


async def test_runner_streams_parsed_lines_to_callback():
    lines = [
        b'{"event": "init", "init": {"model": "gemini-3.8-flash"}}\n{"event": "step_up',
        b'date", "step_update": {"step_type": "tool", "state": "ACTIVE", "tool_name": "run_command"}}\n',
        b'{"event": "result", "result": {"response": "ok"}}\n',
    ]
    container = MagicMock()
    container.logs.return_value = iter(lines)
    container.wait.return_value = {"StatusCode": 0}
    client = MagicMock()
    client.containers.run.return_value = container

    received: list[AgentEvent] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        result = await DockerSandboxRunner(client=client).run_task(
            Task(id="t1", project_id="p1", title="T", description="D"),
            repo_path=tmpdir,
            task_instructions="faça",
            on_event=received.append,
        )

    assert result.exit_code == 0
    assert '"response": "ok"' in result.logs
    assert [e.type for e in received] == [
        AgentEventType.SYSTEM,
        AgentEventType.TOOL_USE,
        AgentEventType.RESULT,
    ]
    assert received[1].text == "run_command"


async def test_dispatch_publishes_and_finishes_activity():
    project = Project(id="p1", name="App", repo_path="/repo")
    task = Task(id="t1", project_id="p1", title="T", description="D")
    tracker = AsyncMock()
    tracker.get_task.return_value = task
    tracker.get_project.return_value = project
    git = AsyncMock()
    git.run_tests.return_value = (0, "ok")
    git.merge_branch.return_value = (0, "ok")
    sandbox = AsyncMock()

    async def run_task(task, repo_path, instructions, on_event=None, **kwargs):
        on_event(_event(AgentEventType.TOOL_USE, "write_file"))
        return ExecutionResult(exit_code=0, logs="")

    sandbox.run_task.side_effect = run_task
    orchestrator = PainkillerOrchestrator(tracker=tracker, sandbox=sandbox, git=git)

    await orchestrator.dispatch_task("t1")

    run = orchestrator.activity.get("t1")
    assert run.done
    texts = [e.text for e in run.events]
    assert "write_file" in texts
    assert any("testes" in t for t in texts)


async def test_stream_route_reports_inactive_task(tmp_path):
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=admin_headers()) as client:
            resp = await client.get("/api/tasks/t-ghost/stream")

    assert resp.status_code == 200
    frames = [f for f in resp.text.split("\n\n") if f.strip()]
    assert frames[0].startswith("event: STATE")
    assert json.loads(frames[0].split("data: ", 1)[1])["active"] is False
    assert frames[-1].startswith("event: CLOSE")


async def test_stream_route_replays_finished_run_with_tool_detail(tmp_path):
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    hub = app.state.orchestrator.activity
    hub.start("t1")
    hub.publish(
        "t1",
        AgentEvent(
            type=AgentEventType.TOOL_USE,
            text="run_command",
            raw={"step_update": {"tool_input": {"command": "pytest -q"}}},
        ),
    )
    hub.finish("t1")

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=admin_headers()) as client:
            resp = await client.get("/api/tasks/t1/stream")

    tool = next(f for f in resp.text.split("\n\n") if f.startswith("event: TOOL_USE"))
    payload = json.loads(tool.split("data: ", 1)[1])
    assert payload["text"] == "run_command"
    assert payload["detail"] == "pytest -q"


async def test_stop_task_route(tmp_path):
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    app.state.orchestrator.stop_task = AsyncMock()

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", headers=admin_headers()) as client:
            resp = await client.post("/api/tasks/task-test-stop/stop")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "stopping"
    assert data["task_id"] == "task-test-stop"
    app.state.orchestrator.stop_task.assert_awaited_once_with("task-test-stop")

