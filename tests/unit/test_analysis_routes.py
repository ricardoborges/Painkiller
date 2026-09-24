"""Integration tests for the analysis routes, including the SSE stream.

The Docker adapter is swapped for an in-memory fake so the whole path
(HTTP -> engine -> port -> SSE frames) is exercised without a daemon.
"""

import asyncio
import json
from typing import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from painkiller.api.server import create_app
from tests.auth_helpers import admin_headers
from painkiller.core.domain.models import AgentEvent, AgentEventType
from painkiller.core.ports.agent_session import AgentSessionPort
from painkiller.engine.analysis import AnalysisOrchestrator


class ScriptedAgent(AgentSessionPort):
    def __init__(self, events: list[AgentEvent]):
        self.events = events
        self.sent: list[str] = []
        self.closed = False

    async def start(
        self,
        session_id,
        repo_path,
        prompt="",
        env=None,
        timeout_seconds=3600,
        resume=False,
        claude_session_id=None,
        harness=None,
        api_key=None,
        **kwargs,
    ) -> str:
        return "pk-analysis-fake"

    async def is_alive(self, session_id) -> bool:
        return True

    async def send(self, session_id, text) -> None:
        self.sent.append(text)

    async def close_input(self, session_id) -> None:
        self.closed = True

    async def stop(self, session_id) -> None:
        pass

    async def stream(self, session_id) -> AsyncIterator[AgentEvent]:
        for event in self.events:
            yield event


@pytest.fixture
async def client(tmp_path):
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    agent = ScriptedAgent(
        [
            AgentEvent(type=AgentEventType.ASSISTANT, text="Qual o objetivo do projeto?"),
            AgentEvent(type=AgentEventType.RESULT, text="Qual o objetivo do projeto?"),
            AgentEvent(type=AgentEventType.EXIT, text="0", raw={"exit_code": 0}),
        ]
    )
    app.state.agent = agent
    app.state.analysis = AnalysisOrchestrator(agent=agent, tracker=app.state.tracker)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=admin_headers()) as c:
        async with app.router.lifespan_context(app):
            c.agent = agent
            yield c


async def _project(client, tmp_path) -> str:
    res = await client.post("/api/projects", json={"name": "Teste", "description": "d", "api_key": "k"})
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def test_start_returns_immediately_with_a_session(client, tmp_path):
    pid = await _project(client, tmp_path)

    res = await client.post(f"/api/projects/{pid}/analysis")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["session_id"].startswith("analysis-")
    assert body["container_name"] == "pk-analysis-fake"


async def test_start_on_unknown_project_is_404(client):
    assert (await client.post("/api/projects/nope/analysis")).status_code == 404


async def test_stream_emits_sse_frames_for_each_event(client, tmp_path):
    pid = await _project(client, tmp_path)
    sid = (await client.post(f"/api/projects/{pid}/analysis")).json()["session_id"]
    await asyncio.sleep(0.05)

    async with client.stream("GET", f"/api/analysis/{sid}/stream") as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        body = ""
        async for chunk in res.aiter_text():
            body += chunk

    assert "event: ASSISTANT" in body
    assert "event: EXIT" in body
    # A última moldura fecha o EventSource do lado do navegador.
    assert body.rstrip().endswith("data: {}")

    payloads = [
        json.loads(line[len("data: "):])
        for line in body.splitlines()
        if line.startswith("data: ") and line != "data: {}"
    ]
    assert payloads[0]["text"] == "Qual o objetivo do projeto?"


async def test_message_reaches_the_agent(client, tmp_path):
    pid = await _project(client, tmp_path)
    sid = (await client.post(f"/api/projects/{pid}/analysis")).json()["session_id"]

    res = await client.post(f"/api/analysis/{sid}/message", json={"answer": "um CRUD"})

    assert res.status_code == 200
    assert client.agent.sent == ["um CRUD"]


async def test_finish_closes_the_agent_input(client, tmp_path):
    pid = await _project(client, tmp_path)
    sid = (await client.post(f"/api/projects/{pid}/analysis")).json()["session_id"]

    assert (await client.post(f"/api/analysis/{sid}/finish")).status_code == 200
    assert client.agent.closed is True


async def test_commit_without_backlog_file_is_409(client, tmp_path):
    pid = await _project(client, tmp_path)
    sid = (await client.post(f"/api/projects/{pid}/analysis")).json()["session_id"]

    res = await client.post(f"/api/analysis/{sid}/commit")

    assert res.status_code == 409
    assert f".painkiller/backlogs/{sid}.json" in res.json()["detail"]


async def test_unknown_session_is_404_on_every_verb(client):
    assert (await client.get("/api/analysis/analysis-nope")).status_code == 404
    assert (await client.get("/api/analysis/analysis-nope/stream")).status_code == 404
    assert (
        await client.post("/api/analysis/analysis-nope/message", json={"answer": "x"})
    ).status_code == 404


async def test_current_analysis_route(client, tmp_path):
    pid = await _project(client, tmp_path)

    # Inicialmente nenhuma análise ativa
    initial = await client.get(f"/api/projects/{pid}/analysis/current")
    assert initial.status_code == 200
    assert initial.json()["session"] is None

    # Inicia análise
    start_res = await client.post(f"/api/projects/{pid}/analysis")
    assert start_res.status_code == 200
    sid = start_res.json()["session_id"]

    # Consulta novamente: deve retornar a sessão ativa
    current = await client.get(f"/api/projects/{pid}/analysis/current")
    assert current.status_code == 200
    assert current.json()["session"]["session_id"] == sid

