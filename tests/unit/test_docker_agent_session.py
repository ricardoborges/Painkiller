"""Unit tests for the Docker adapter behind the interactive analysis session.

Docker itself is mocked: what matters here is the container contract (command,
mount, credentials) and the file-backed stdin queue the in-container bridge polls.
"""

import json
from unittest.mock import MagicMock

import pytest

from painkiller.adapters.sandbox.docker_agent_session import (
    EOF_SENTINEL,
    DockerAgentSession,
)
from painkiller.core.domain.models import AgentEventType


@pytest.fixture(autouse=True)
def anthropic_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("PAINKILLER_CONTAINER_ROOT", raising=False)
    monkeypatch.delenv("PAINKILLER_HOST_ROOT", raising=False)
    monkeypatch.delenv("PAINKILLER_AGENT_MODEL", raising=False)


@pytest.fixture
def client():
    fake = MagicMock()
    fake.containers.run.return_value = MagicMock()
    return fake


def _queue_lines(tmp_path):
    text = (tmp_path / ".painkiller" / "agent-stdin.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


async def test_start_runs_claude_in_bidirectional_stream_mode(tmp_path, client):
    session = DockerAgentSession(client=client)

    await session.start("analysis-1", str(tmp_path), "Comece a entrevista")

    command = client.containers.run.call_args.kwargs["command"]
    assert command[:2] == ["painkiller", "agent-run"]
    agent_args = command[command.index("--") + 1:]
    # Sem os dois stream-json não existe conversa: seria one-shot como o Aider.
    assert "--input-format" in agent_args and agent_args[agent_args.index("--input-format") + 1] == "stream-json"
    assert "--output-format" in agent_args and agent_args[agent_args.index("--output-format") + 1] == "stream-json"
    assert agent_args[agent_args.index("--plugin-dir") + 1] == "/opt/superpowers"


async def test_start_mounts_the_repo_and_seeds_the_prompt_into_the_queue(tmp_path, client):
    session = DockerAgentSession(client=client)

    await session.start("analysis-1", str(tmp_path), "Comece a entrevista")

    volumes = client.containers.run.call_args.kwargs["volumes"]
    assert list(volumes.values())[0]["bind"] == "/workspace"
    # O prompt inicial viaja pela mesma fila das respostas do analista.
    assert _queue_lines(tmp_path) == [
        {"type": "user", "message": {"role": "user", "content": "Comece a entrevista"}}
    ]


async def test_send_appends_an_analyst_turn(tmp_path, client):
    session = DockerAgentSession(client=client)
    await session.start("analysis-1", str(tmp_path), "prompt")

    await session.send("analysis-1", "quero um CRUD")

    assert _queue_lines(tmp_path)[-1]["message"]["content"] == "quero um CRUD"


async def test_close_input_writes_the_eof_sentinel(tmp_path, client):
    session = DockerAgentSession(client=client)
    await session.start("analysis-1", str(tmp_path), "prompt")

    await session.close_input("analysis-1")

    assert _queue_lines(tmp_path)[-1] == {"type": EOF_SENTINEL}


async def test_missing_anthropic_credentials_fail_before_the_container_starts(tmp_path, client, monkeypatch):
    # As chaves NVIDIA/LiteLLM do resto da plataforma não servem para o Claude Code.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-xxx")
    session = DockerAgentSession(client=client)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
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
