"""Unit tests for the Maki (maki.sh) harness.

Maki speaks Claude Code's stream-json in both directions, so it reuses the
`painkiller agent-run` queue bridge of the Antigravity path. What is specific to
it: the DeepSeek key, session ids chosen by Painkiller, a state directory that
outlives the container, and errors reported inside a `result` with exit 0.
"""

import json
import sys
import textwrap
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from painkiller.adapters.sandbox.docker_agent_session import (
    DockerAgentSession,
    maki_session_file,
    parse_agent_line,
)
from painkiller.adapters.sandbox.docker_runner import DockerSandboxRunner
from painkiller.cli import agent_run as bridge
from painkiller.core.domain.models import AgentEventType, Task, TaskStatus
from painkiller.core.usage import parse_task_usage

SESSION = "12345678-1234-4234-8234-123456789012"

#: Linhas reais do `maki --print --output-format stream-json` 0.5.6.
INIT = {"type": "system", "subtype": "init", "cwd": "/w", "session_id": SESSION, "model": "deepseek-v4-flash"}
OK_RESULT = {
    "type": "result", "subtype": "success", "is_error": False, "num_turns": 1, "result": "ok",
    "total_cost_usd": 3.8748e-05, "session_id": SESSION,
    "usage": {"input_tokens": 134, "output_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 6016},
}
AUTH_RESULT = {
    "type": "result", "subtype": "error", "is_error": True, "num_turns": 0,
    "result": "authentication failed, run `maki auth login` or check your API key",
    "total_cost_usd": 0.0, "session_id": SESSION,
    "usage": {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-global")
    for name in ("PAINKILLER_MAKI_MODEL", "PAINKILLER_CONTAINER_ROOT", "PAINKILLER_HOST_ROOT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client():
    fake = MagicMock()
    fake.containers.run.return_value = MagicMock()
    return fake


def _agent_args(command):
    return command[command.index("--") + 1:]


# ---- sessão de análise ------------------------------------------------------


async def test_start_runs_maki_in_bidirectional_stream_mode(tmp_path, client):
    session = DockerAgentSession(client=client)

    await session.start(
        "analysis-maki", str(tmp_path), "Comece", claude_session_id=SESSION,
        harness="maki_superpowers", api_key="sk-project",
    )

    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["image"] == "painkiller-agent-maki:latest"
    command = kwargs["command"]
    assert command[:4] == ["painkiller", "agent-run", "--agent-bin", "maki"]
    assert "--fail-on-error-result" in command
    assert "--stdin-offset" not in command
    args = _agent_args(command)
    for flag in ("--trust", "--yolo", "--print", "--include-partial-messages"):
        assert flag in args
    assert args[args.index("--input-format") + 1] == "stream-json"
    assert args[args.index("--output-format") + 1] == "stream-json"
    assert args[args.index("--model") + 1] == "deepseek/deepseek-v4-pro"
    assert args[args.index("--session-id") + 1] == SESSION
    # A mesma chave DeepSeek do projeto, não a do .env.
    assert kwargs["environment"]["DEEPSEEK_API_KEY"] == "sk-project"
    binds = {v["bind"] for v in kwargs["volumes"].values()}
    assert binds == {"/workspace", "/root/.local/state/maki"}
    # Sem `sessions/` o maki não grava a sessão no diretório montado.
    assert (tmp_path / ".painkiller" / "maki_home" / "sessions" / "locks").is_dir()


async def test_model_can_be_overridden(tmp_path, client, monkeypatch):
    monkeypatch.setenv("PAINKILLER_MAKI_MODEL", "deepseek/deepseek-v4-pro")
    await DockerAgentSession(client=client).start(
        "a", str(tmp_path), "p", claude_session_id=SESSION, harness="maki_superpowers",
    )
    args = _agent_args(client.containers.run.call_args.kwargs["command"])
    assert args[args.index("--model") + 1] == "deepseek/deepseek-v4-pro"


async def test_resume_continues_saved_session_after_answered_queue(tmp_path, client):
    sessions = tmp_path / ".painkiller" / "maki_home" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / maki_session_file(SESSION)).write_text("{}\n", encoding="utf-8")
    queue = tmp_path / ".painkiller" / "agent-stdin.jsonl"
    queue.write_text('{"type": "user", "message": {"content": "já respondida"}}\n', encoding="utf-8")

    await DockerAgentSession(client=client).start(
        "a", str(tmp_path), "", resume=True, claude_session_id=SESSION, harness="maki_superpowers",
    )

    command = client.containers.run.call_args.kwargs["command"]
    assert command[command.index("--stdin-offset") + 1] == str(queue.stat().st_size)
    args = _agent_args(command)
    assert args[args.index("--session") + 1] == SESSION
    assert "--session-id" not in args


async def test_resume_without_saved_session_starts_under_same_id(tmp_path, client):
    # O contêiner caiu antes do primeiro turno: `--session` falharia.
    await DockerAgentSession(client=client).start(
        "a", str(tmp_path), "", resume=True, claude_session_id=SESSION, harness="maki_superpowers",
    )
    args = _agent_args(client.containers.run.call_args.kwargs["command"])
    assert args[args.index("--session-id") + 1] == SESSION
    assert "--session" not in args


async def test_missing_deepseek_key_fails_early(tmp_path, client, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        await DockerAgentSession(client=client).start("a", str(tmp_path), "p", harness="maki_superpowers")
    client.containers.run.assert_not_called()


def test_maki_session_file_is_base58_of_the_uuid():
    # Conferido contra o maki 0.5.6: --session-id <uuid> grava sessions/<base58>.jsonl.
    assert maki_session_file(SESSION) == "3FP9SaFPAY5Y2N8r97jXhT.jsonl"
    assert maki_session_file("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee") == "N5L7eAvjhw3YjcJmKwA8e9.jsonl"


# ---- parser ---------------------------------------------------------------


def test_parse_maki_stream():
    assert parse_agent_line(json.dumps(INIT)).raw["model"] == "deepseek-v4-flash"
    delta = parse_agent_line(json.dumps({
        "type": "stream_event",
        "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Ol"}},
    }))
    assert delta.type == AgentEventType.ASSISTANT_DELTA and delta.text == "Ol"
    tool = parse_agent_line(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "list", "input": {"path": "/w"}}]},
    }))
    assert tool.type == AgentEventType.TOOL_USE and tool.text == "list"
    result = parse_agent_line(json.dumps(OK_RESULT))
    assert result.type == AgentEventType.RESULT and result.text == "ok"


def test_error_result_is_a_harness_error():
    event = parse_agent_line(json.dumps(AUTH_RESULT))
    assert event.type == AgentEventType.ERROR
    assert event.raw["harness_error"] == "AUTH"
    assert "recusou a chave" in event.text


# ---- execução de tarefa -----------------------------------------------------


def _runner(logs, status=0):
    client = MagicMock()
    container = MagicMock()
    container.logs.return_value = [(json.dumps(line) + "\n").encode() for line in logs]
    container.wait.return_value = {"StatusCode": status}
    client.containers.run.return_value = container
    return DockerSandboxRunner(client=client), client


def _task():
    return Task(id="t-maki", project_id="p1", title="T", description="d", status=TaskStatus.READY)


async def test_runner_runs_maki_one_shot():
    runner, client = _runner([INIT, OK_RESULT])

    res = await runner.run_task(
        task=_task(), repo_path="/fake/repo", task_instructions="Implemente X",
        harness="maki_superpowers", api_key="sk-project",
    )

    assert res.exit_code == 0
    args, kwargs = client.containers.run.call_args
    assert args[0] == "painkiller-worker-maki:latest"
    assert kwargs["command"] == [
        "maki", "--trust", "--yolo", "--print", "--output-format", "stream-json",
        "--include-partial-messages", "--model", "deepseek/deepseek-v4-pro", "Implemente X",
    ]
    assert kwargs["environment"]["DEEPSEEK_API_KEY"] == "sk-project"


async def test_runner_treats_error_result_as_failure():
    # O maki sai com 0; sem isto a tarefa iria para os testes e para o review.
    runner, _ = _runner([INIT, AUTH_RESULT], status=0)
    res = await runner.run_task(
        task=_task(), repo_path="/fake/repo", task_instructions="x", harness="maki_superpowers",
    )
    assert res.exit_code == 1


def test_task_usage_takes_model_from_init():
    logs = "\n".join(json.dumps(line) for line in (INIT, OK_RESULT))
    assert parse_task_usage(logs) == (134 + 6016, 1, 3.8748e-05, "deepseek-v4-flash")


# ---- ponte agent-run --------------------------------------------------------

FAKE_AGENT = textwrap.dedent(
    r'''
    import json, sys, time
    mode = sys.argv[1]
    for line in sys.stdin:
        text = json.loads(line)["message"]["content"]
        if mode == "hang":
            # O maki real no modo SDK: a chave recusada só vai para o log.
            with open(sys.argv[2], "a") as log:
                log.write(json.dumps({"level": "WARN", "fields": {
                    "message": "auth error, waiting for re-authentication",
                    "error": "API error (401): Authentication Fails"}}) + "\n")
            time.sleep(60)
        elif mode == "fail":
            print(json.dumps({"type": "result", "is_error": True, "result": "authentication failed"}), flush=True)
        else:
            print(json.dumps({"type": "result", "is_error": False, "result": "eco " + text}), flush=True)
    '''
)


@pytest.fixture
def fake_agent(tmp_path):
    script = tmp_path / "fake_agent.py"
    script.write_text(FAKE_AGENT, encoding="utf-8")
    queue = tmp_path / "q.jsonl"
    return script, queue


def _run_bridge(script, queue, mode, *extra, agent_args=()):
    return CliRunner().invoke(
        bridge.agent_run,
        ["--stdin-file", str(queue), "--agent-bin", sys.executable, "--idle-timeout", "20",
         "--fail-on-error-result", *extra, "--", str(script), mode, *agent_args],
        catch_exceptions=False,
    )


def _msg(text):
    return json.dumps({"event": "user", "type": "user", "message": {"role": "user", "content": text}}) + "\n"


def test_bridge_stops_on_error_result(fake_agent):
    script, queue = fake_agent
    queue.write_text(_msg("oi"), encoding="utf-8")

    result = _run_bridge(script, queue, "fail")

    assert result.exit_code == 1
    assert '"is_error": true' in result.output


def test_bridge_skips_answered_queue_on_resume(fake_agent):
    script, queue = fake_agent
    queue.write_text(_msg("antiga"), encoding="utf-8")
    answered = queue.stat().st_size
    with open(queue, "a", encoding="utf-8") as f:
        f.write(_msg("nova"))
        f.write(json.dumps({"type": "__painkiller_eof__"}) + "\n")

    result = _run_bridge(script, queue, "ok", "--stdin-offset", str(answered))

    assert result.exit_code == 0
    assert "eco nova" in result.output
    assert "eco antiga" not in result.output


def test_bridge_stops_on_fatal_error_only_in_agent_log(fake_agent, tmp_path):
    script, queue = fake_agent
    log = tmp_path / "maki.log"
    queue.write_text(_msg("oi"), encoding="utf-8")

    result = _run_bridge(script, queue, "hang", "--agent-log", str(log), agent_args=(str(log),))

    assert result.exit_code == 1
    synthetic = [json.loads(l) for l in result.output.splitlines() if l.startswith("{")][-1]
    assert synthetic["is_error"] is True
    # O mesmo caminho de erro visível dos outros harnesses.
    event = parse_agent_line(json.dumps(synthetic))
    assert event.raw["harness_error"] == "AUTH"
