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


#: Chave do projeto; a única que chega ao contêiner.
KEY = "AIzaSyTestKey123"

@pytest.fixture(autouse=True)
def gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSy-global-not-forwarded")
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

    await session.start("analysis-1", str(tmp_path), "Comece a entrevista", api_key=KEY)

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
    # Só a chave do projeto entra; a do ambiente do servidor não é repassada.
    assert client.containers.run.call_args.kwargs["environment"]["GEMINI_API_KEY"] == KEY


async def test_start_mounts_the_repo_and_seeds_the_prompt_into_the_queue(tmp_path, client):
    session = DockerAgentSession(client=client)

    await session.start("analysis-1", str(tmp_path), "Comece a entrevista", api_key=KEY)

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
    await session.start("analysis-1", str(tmp_path), "prompt", api_key=KEY)

    await session.send("analysis-1", "quero um CRUD")

    last = _queue_lines(tmp_path)[-1]
    assert last["message"]["content"] == "quero um CRUD"
    assert last.get("event") == "user" or last.get("type") == "user"


async def test_close_input_writes_the_eof_sentinel(tmp_path, client):
    session = DockerAgentSession(client=client)
    await session.start("analysis-1", str(tmp_path), "prompt", api_key=KEY)

    await session.close_input("analysis-1")

    assert _queue_lines(tmp_path)[-1] == {"type": EOF_SENTINEL}


async def test_project_without_key_fails_before_the_container_starts(tmp_path, client):
    # A chave global do .env (GEMINI_API_KEY da fixture) não serve mais de fallback.
    session = DockerAgentSession(client=client)

    with pytest.raises(RuntimeError, match="chave de API"):
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
    await session.start("analysis-1", str(tmp_path), "prompt", api_key=KEY)

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
    await session.start("analysis-1", str(tmp_path), "prompt", api_key=KEY)

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


async def test_stop_finds_container_in_docker_when_not_cached(client):
    fake_container = MagicMock()
    client.containers.list.return_value = [fake_container]
    session = DockerAgentSession(client=client)

    await session.stop("analysis-ghost")

    client.containers.list.assert_called_once_with(
        all=True, filters={"name": "pk-analysis-analysis-ghost"}
    )
    fake_container.remove.assert_called_once_with(force=True)


async def test_cleanup_orphaned_containers_removes_untracked_and_dead_containers(client):
    c1 = MagicMock(status="running")
    c1.name = "pk-analysis-analysis-old-111"
    c2 = MagicMock(status="running")
    c2.name = "pk-analysis-analysis-active-222"
    c3 = MagicMock(status="exited")
    c3.name = "pk-analysis-analysis-dead-333"

    client.containers.list.return_value = [c1, c2, c3]
    session = DockerAgentSession(client=client)

    cleaned = await session.cleanup_orphaned_containers(
        active_session_ids={"analysis-active-222"}
    )

    assert "pk-analysis-analysis-old-111" in cleaned
    assert "pk-analysis-analysis-dead-333" in cleaned
    assert "pk-analysis-analysis-active-222" not in cleaned

    c1.remove.assert_called_once_with(force=True)
    c3.remove.assert_called_once_with(force=True)
    c2.remove.assert_not_called()


async def test_start_runs_dsh_for_deepseek_harness(tmp_path, client):
    session = DockerAgentSession(client=client)

    await session.start(
        "analysis-dsh",
        str(tmp_path),
        "Comece a entrevista",
        harness="deepseek_superpowers",
        api_key="sk-ds-project-key",
    )

    run_kwargs = client.containers.run.call_args.kwargs
    assert run_kwargs["image"] == "painkiller-agent-deepseek:latest"
    command = run_kwargs["command"]
    assert command[:4] == ["painkiller", "acp-run", "--stdin-file", "/workspace/.painkiller/agent-stdin.jsonl"]
    assert "--resume" not in command
    assert run_kwargs["environment"]["DEEPSEEK_API_KEY"] == "sk-ds-project-key"
    # O histórico do dsh vive fora do contêiner, para a retomada achar a sessão.
    binds = {v["bind"] for v in run_kwargs["volumes"].values()}
    assert {"/workspace", "/root/.dsh/sessions", "/root/.dsh/storages"} <= binds


async def test_resume_deepseek_passes_session_key(tmp_path, client):
    session = DockerAgentSession(client=client)

    await session.start(
        "analysis-dsh",
        str(tmp_path),
        "",
        resume=True,
        claude_session_id="pk-conv-1",
        harness="deepseek_superpowers",
        api_key="sk-ds-project-key",
    )

    command = client.containers.run.call_args.kwargs["command"]
    assert command[command.index("--session-key") + 1] == "pk-conv-1"
    assert "--resume" in command
    # Medido antes de qualquer envio: a fila existente já foi respondida.
    assert command[command.index("--stdin-offset") + 1] == "0"


async def test_missing_deepseek_credentials_fail_with_clear_error(tmp_path, client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-global-not-used")
    session = DockerAgentSession(client=client)

    with pytest.raises(RuntimeError, match="chave de API"):
        await session.start(
            "analysis-dsh",
            str(tmp_path),
            "prompt",
            harness="deepseek_superpowers",
        )

    client.containers.run.assert_not_called()


def test_parse_dsh_json_lines():
    # Delta
    ev_delta = parse_agent_line(json.dumps({"type": "delta", "text": "Olá"}))
    assert ev_delta is not None
    assert ev_delta.type == AgentEventType.ASSISTANT_DELTA
    assert ev_delta.text == "Olá"

    # Tool use
    ev_tool = parse_agent_line(json.dumps({"type": "tool_call", "name": "run_command"}))
    assert ev_tool is not None
    assert ev_tool.type == AgentEventType.TOOL_USE
    assert ev_tool.text == "run_command"

    # Result
    ev_res = parse_agent_line(json.dumps({"type": "result", "content": "Concluído com sucesso"}))
    assert ev_res is not None
    assert ev_res.type == AgentEventType.RESULT
    assert ev_res.text == "Concluído com sucesso"



def test_parse_dsh_quota_is_a_fatal_error_in_portuguese():
    event = parse_agent_line("dsh: QUOTA: Insufficient Balance")
    assert event is not None
    assert event.type == AgentEventType.ERROR
    assert event.raw["harness_error"] == "QUOTA"
    assert event.raw["detail"] == "Insufficient Balance"
    assert "sem saldo" in event.text


def test_parse_dsh_auth_and_fatal_are_errors():
    auth = parse_agent_line("dsh: AUTH: invalid api key")
    assert auth.type == AgentEventType.ERROR
    assert auth.raw["harness_error"] == "AUTH"

    fatal = parse_agent_line("dsh: fatal: profile not found")
    assert fatal.type == AgentEventType.ERROR
    assert fatal.raw["harness_error"] == "FATAL"
    assert "profile not found" in fatal.text


def test_parse_dsh_reasoning_and_status_lines_are_not_errors():
    assert parse_agent_line("dsh: reasoning: pensando").type == AgentEventType.THINKING_DELTA
    status = parse_agent_line("dsh: booting profile headless")
    assert status.type == AgentEventType.SYSTEM
    assert "harness_error" not in status.raw


async def test_missing_image_explains_how_to_build_it(tmp_path, client):
    import docker.errors

    client.containers.run.side_effect = docker.errors.ImageNotFound("pull access denied")
    session = DockerAgentSession(client=client)

    with pytest.raises(RuntimeError, match=r"docker compose --profile build build"):
        await session.start("analysis-x", str(tmp_path), "p", api_key=KEY)


async def test_agy_model_and_effort_come_from_the_project(tmp_path, client, monkeypatch):
    monkeypatch.setenv("PAINKILLER_AGENT_MODEL", "from-env")
    monkeypatch.setenv("PAINKILLER_AGENT_EFFORT", "low")
    session = DockerAgentSession(client=client)

    await session.start("a", str(tmp_path), "p", api_key=KEY, model="gemini-3.8-pro", effort="high")
    command = client.containers.run.call_args.kwargs["command"]
    args = command[command.index("--") + 1:]
    assert args[args.index("--model") + 1] == "gemini-3.8-pro"
    assert args[args.index("--effort") + 1] == "high"
    assert "PAINKILLER_AGENT_MODEL" not in client.containers.run.call_args.kwargs["environment"]

    # Projeto sem escolha: padrões do harness, nunca o .env.
    await session.start("b", str(tmp_path), "p", api_key=KEY)
    command = client.containers.run.call_args.kwargs["command"]
    args = command[command.index("--") + 1:]
    assert args[args.index("--model") + 1] == "gemini-3.8-flash"
    assert args[args.index("--effort") + 1] == "medium"


async def test_dsh_receives_the_project_model_and_effort(tmp_path, client):
    await DockerAgentSession(client=client).start(
        "a", str(tmp_path), "p", harness="deepseek_superpowers", api_key="sk-ds", model="deepseek-v4-flash", effort="low",
    )
    env = client.containers.run.call_args.kwargs["environment"]
    assert env["PAINKILLER_DEEPSEEK_MODEL"] == "deepseek-v4-flash"
    assert env["PAINKILLER_DEEPSEEK_EFFORT"] == "low"
