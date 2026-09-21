"""Unit tests for the Docker adapter behind the interactive analysis session (Antigravity CLI + Superpowers).

Docker itself is mocked: what matters here is the container contract (command,
mount, credentials) and the file-backed stdin queue the in-container bridge polls.
"""

import json
from unittest.mock import MagicMock

import pytest

from painkiller.adapters.sandbox.docker_agent_session import (
    EOF_SENTINEL,
    DockerAgentSession,
    parse_agent_line,
)
from painkiller.core.domain.models import AgentEventType


@pytest.fixture(autouse=True)
def gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTestKey123")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PAINKILLER_CONTAINER_ROOT", raising=False)
    monkeypatch.delenv("PAINKILLER_HOST_ROOT", raising=False)
    monkeypatch.delenv("PAINKILLER_AGENT_MODEL", raising=False)
    monkeypatch.delenv("PAINKILLER_AGENT_EFFORT", raising=False)


@pytest.fixture
def client():
    fake = MagicMock()
    fake.containers.run.return_value = MagicMock()
    return fake


def _queue_lines(tmp_path):
    text = (tmp_path / ".painkiller" / "agent-stdin.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


async def test_start_runs_agy_in_bidirectional_stream_mode(tmp_path, client):
    session = DockerAgentSession(client=client)

    await session.start("analysis-1", str(tmp_path), "Comece a entrevista")

    command = client.containers.run.call_args.kwargs["command"]
    assert command[:4] == ["painkiller", "agent-run", "--agent-bin", "agy"]
    agent_args = command[command.index("--") + 1:]
    # Sem os dois stream-json não existe conversa: seria como o modo print.
    assert "--input-format" in agent_args and agent_args[agent_args.index("--input-format") + 1] == "stream-json"
    assert "--output-format" in agent_args and agent_args[agent_args.index("--output-format") + 1] == "stream-json"
    assert "--dangerously-skip-permissions" in agent_args
    assert "--model" in agent_args and agent_args[agent_args.index("--model") + 1] == "gemini-3.8-flash"
    assert "--effort" in agent_args and agent_args[agent_args.index("--effort") + 1] == "medium"
    assert not any(arg.startswith("--print") for arg in agent_args)


async def test_start_mounts_the_repo_and_seeds_the_prompt_into_the_queue(tmp_path, client):
    session = DockerAgentSession(client=client)

    await session.start("analysis-1", str(tmp_path), "Comece a entrevista")

    volumes = client.containers.run.call_args.kwargs["volumes"]
    bindings = [v["bind"] for v in volumes.values()]
    assert "/workspace" in bindings
    assert "/root/.gemini" in bindings

    # O prompt inicial viaja pela mesma fila das respostas do analista, formatado com event e type.
    first = _queue_lines(tmp_path)[0]
    assert first.get("event") == "user" or first.get("type") == "user"
    assert first["message"]["content"] == "Comece a entrevista"

    # Configurações do agy devem ser inicializadas para autenticar com GEMINI_API_KEY
    settings_file = tmp_path / ".painkiller" / "gemini_home" / "antigravity-cli" / "settings.json"
    assert settings_file.exists()
    assert json.loads(settings_file.read_text(encoding="utf-8"))["modelProvider"] == "gemini"


async def test_send_appends_an_analyst_turn(tmp_path, client):
    session = DockerAgentSession(client=client)
    await session.start("analysis-1", str(tmp_path), "prompt")

    await session.send("analysis-1", "quero um CRUD")

    last = _queue_lines(tmp_path)[-1]
    assert last["message"]["content"] == "quero um CRUD"
    assert last.get("event") == "user" or last.get("type") == "user"


async def test_close_input_writes_the_eof_sentinel(tmp_path, client):
    session = DockerAgentSession(client=client)
    await session.start("analysis-1", str(tmp_path), "prompt")

    await session.close_input("analysis-1")

    assert _queue_lines(tmp_path)[-1] == {"type": EOF_SENTINEL}


async def test_missing_gemini_credentials_fail_before_the_container_starts(tmp_path, client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    session = DockerAgentSession(client=client)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        await session.start("analysis-1", str(tmp_path), "prompt")

    client.containers.run.assert_not_called()


async def test_send_to_an_unknown_session_is_rejected(tmp_path, client):
    session = DockerAgentSession(client=client)
    with pytest.raises(ValueError):
        await session.send("analysis-nope", "oi")


async def test_stream_splits_chunks_that_are_not_line_aligned(tmp_path, client):
    container = client.containers.run.return_value
    # docker-py entrega bytes arbitrários, não linhas: um JSON pode chegar partido.
    container.logs.return_value = iter([
        b'{"type":"assistant","message":{"content":[{"type":"text","te',
        b'xt":"Qual o objetivo?"}]}}\n{"type":"result","result":"ok"}\n',
    ])
    container.wait.return_value = {"StatusCode": 0}
    session = DockerAgentSession(client=client)
    await session.start("analysis-1", str(tmp_path), "prompt")

    events = [e async for e in session.stream("analysis-1")]

    assert [e.type for e in events] == [
        AgentEventType.ASSISTANT,
        AgentEventType.RESULT,
        AgentEventType.EXIT,
    ]
    assert events[0].text == "Qual o objetivo?"
    assert events[-1].raw["exit_code"] == 0


async def test_stream_parses_agy_events(tmp_path, client):
    container = client.containers.run.return_value
    container.logs.return_value = iter([
        b'{"event":"init","conversation_id":"cid-1","init":{"model":"gemini-3.8-flash"}}\n',
        b'{"event":"step_update","step_update":{"conversation_id":"cid-1","step_type":"agent_response","text_delta":"Qual o "}}\n',
        b'{"event":"step_update","step_update":{"conversation_id":"cid-1","step_type":"agent_response","text_delta":"objetivo?"}}\n',
        b'{"event":"step_update","step_update":{"conversation_id":"cid-1","step_type":"tool","tool_name":"list_dir","state":"ACTIVE"}}\n',
        b'{"event":"step_update","step_update":{"conversation_id":"cid-1","step_type":"tool","tool_name":"list_dir","state":"DONE"}}\n',
        b'{"event":"result","result":{"conversation_id":"cid-1","status":"SUCCESS","response":"Qual o objetivo?"}}\n',
    ])
    container.wait.return_value = {"StatusCode": 0}
    session = DockerAgentSession(client=client)
    await session.start("analysis-1", str(tmp_path), "prompt")

    events = [e async for e in session.stream("analysis-1")]

    assert [e.type for e in events] == [
        AgentEventType.SYSTEM,
        AgentEventType.ASSISTANT_DELTA,
        AgentEventType.ASSISTANT_DELTA,
        AgentEventType.TOOL_USE,
        AgentEventType.TOOL_RESULT,
        AgentEventType.RESULT,
        AgentEventType.EXIT,
    ]
    assert events[1].text == "Qual o "
    assert events[2].text == "objetivo?"
    assert events[3].text == "list_dir"
    assert events[5].text == "Qual o objetivo?"
    assert events[-1].raw["exit_code"] == 0
