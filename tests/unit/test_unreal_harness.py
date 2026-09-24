"""Unit tests for the Unreal Agent harness.

The runner output below follows `sessionstore.Item` of unreallabsai/unreal-agent
at the commit pinned in docker/unreal-*.Dockerfile: `{Sequence, RecordedAt,
Kind, Data}`, with `llm.Response` (`Output`, `Usage`, `Failure`) inside
`model_response`. If a runner upgrade changes it, these are the tests to redo.
"""

import json
import os
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from painkiller.adapters.sandbox.docker_agent_session import parse_agent_line, unreal_model
from painkiller.cli import unreal_run as bridge
from painkiller.core.domain.models import AgentEventType
from painkiller.core.usage import parse_agent_usage, parse_task_usage

SESSION = "12345678-1234-4234-8234-123456789012"


def _item(seq, kind, data):
    return json.dumps({"Sequence": seq, "RecordedAt": "2026-09-23T12:00:00Z", "Kind": kind, "Data": data})


def _response(output, usage=None, failure=None):
    response = {"ID": "resp", "Stop": "complete", "Output": output, "Usage": usage or {}}
    if failure:
        response["Failure"] = failure
    return {"TurnID": "turn-1", "Response": response}


def _message(text):
    return {"Type": "message", "Data": {"Role": "assistant", "Text": text, "Phase": ""}}


def _tool_call(call_id, name):
    return {"Type": "tool_call", "Data": {"CallID": call_id, "Name": name, "Arguments": "{}"}}


A_TURN = [
    _item(1, "input", {"ID": "in-1", "Kind": "external", "Payload": "Oi"}),
    _item(2, "turn", {"ID": "turn-1", "PreviousTurnID": "", "Type": "regular"}),
    _item(3, "model_response", _response(
        [_message("Vou olhar o projeto."), _tool_call("call-1", "bash")],
        usage={"InputTokens": 100, "OutputTokens": 20},
    )),
    _item(4, "tool_call_status", {"TurnID": "turn-1", "CallID": "call-1", "Status": {"WaitingFor": ["op-1"]}}),
    _item(5, "tool_call_status", {"TurnID": "turn-1", "CallID": "call-1", "Status": {"Error": ""}}),
    _item(6, "model_response", _response(
        [_message("Qual banco de dados você usa?")],
        usage={"InputTokens": 300, "OutputTokens": 50},
    )),
]


class FakeProc:
    """Stands in for the unreal-agent-runner process."""

    def __init__(self, stdout_lines, returncode=0, stderr_lines=()):
        self.stdin = _Recorder()
        self.stdout = iter([line + "\n" for line in stdout_lines])
        self.stderr = iter([line + "\n" for line in stderr_lines])
        self.returncode = returncode

    def wait(self):
        return self.returncode


class _Recorder:
    def __init__(self):
        self.data = ""

    def write(self, text):
        self.data += text

    def close(self):
        pass


@pytest.fixture
def runner_output(monkeypatch):
    """Make `_run_turn` spawn a FakeProc; returns the list of spawned (cmd, proc)."""
    spawned = []
    script = {"lines": [], "returncode": 0, "stderr": []}

    def fake_popen(cmd, **kwargs):
        proc = FakeProc(script["lines"], script["returncode"], script["stderr"])
        spawned.append((cmd, proc))
        return proc

    monkeypatch.setattr(bridge.subprocess, "Popen", fake_popen)
    return script, spawned


def _events(out):
    return [parse_agent_line(line) for line in out.splitlines() if line.strip()]


# ---- a ponte -------------------------------------------------------------


def test_turn_is_translated_and_closed_once(runner_output, capsys):
    script, spawned = runner_output
    script["lines"] = A_TURN

    ok = bridge._run_turn("unreal-agent-runner", "/workspace", "/sessions", SESSION, "deepseek-v4-pro", "Oi")

    assert ok
    events = [e for e in _events(capsys.readouterr().out) if e is not None]
    types = [e.type for e in events]
    assert types == [
        AgentEventType.ASSISTANT,
        AgentEventType.TOOL_USE,
        AgentEventType.TOOL_RESULT,
        AgentEventType.ASSISTANT,
        AgentEventType.RESULT,
    ]
    # O texto intermediário não fecha o turno; o RESULT vem só no fim, com a última fala.
    assert events[1].text == "bash" and events[2].text == "bash"
    assert events[-1].text == "Qual banco de dados você usa?"

    # O uso somado das duas chamadas ao modelo chega à contabilidade.
    assert parse_agent_usage(events[-1].raw) == (400, 70, None, "deepseek-v4-pro")

    cmd, proc = spawned[0]
    assert cmd == ["unreal-agent-runner", "-workspace", "/workspace", "-session-directory", "/sessions"]
    assert json.loads(proc.stdin.data) == {
        "messages": [{"role": "user", "content": "Oi"}],
        "session_id": SESSION,
    }


def test_runner_error_becomes_harness_error(runner_output, capsys):
    script, _ = runner_output
    script["lines"] = [json.dumps({"type": "error", "message": "run coordinator: 401 Unauthorized: invalid API key"})]
    script["returncode"] = 1
    script["stderr"] = ["unreal-agent-runner: run coordinator: 401 Unauthorized"]

    ok = bridge._run_turn("unreal-agent-runner", "/workspace", "/sessions", SESSION, "m", "Oi")

    assert not ok
    events = [e for e in _events(capsys.readouterr().out) if e is not None]
    # stderr vira SYSTEM, não ruído de erro.
    assert events[0].type == AgentEventType.SYSTEM
    assert events[-1].type == AgentEventType.ERROR
    assert events[-1].raw["harness_error"] == "AUTH"
    assert AgentEventType.RESULT not in [e.type for e in events]


def test_model_failure_fails_the_turn_even_on_exit_zero(runner_output, capsys):
    script, _ = runner_output
    script["lines"] = [
        _item(1, "model_response", _response([], failure={"Code": "402", "Message": "Insufficient Balance"})),
    ]

    ok = bridge._run_turn("unreal-agent-runner", "/workspace", "/sessions", None, "m", "Oi")

    assert not ok
    last = [e for e in _events(capsys.readouterr().out) if e is not None][-1]
    assert last.type == AgentEventType.ERROR
    assert last.raw["harness_error"] == "QUOTA"


def test_task_logs_yield_usage_and_failure_summary(runner_output, capsys):
    from painkiller.adapters.sandbox.docker_runner import DockerSandboxRunner

    script, _ = runner_output
    script["lines"] = A_TURN
    bridge._run_turn("unreal-agent-runner", "/workspace", "/sessions", None, "deepseek-v4-pro", "Faça X")
    logs = capsys.readouterr().out

    assert parse_task_usage(logs) == (400, 70, None, "deepseek-v4-pro")
    assert not DockerSandboxRunner._ended_in_error(logs)


def test_stdin_offset_skips_answered_messages(tmp_path, monkeypatch):
    queue = tmp_path / "agent-stdin.jsonl"
    first = json.dumps({"type": "user", "message": {"content": "já respondida"}}) + "\n"
    rest = (
        json.dumps({"type": "user", "message": {"content": "nova"}}) + "\n"
        + json.dumps({"type": "__painkiller_eof__"}) + "\n"
    )
    queue.write_text(first + rest, encoding="utf-8")

    seen = []
    monkeypatch.setattr(bridge, "_run_turn", lambda *args: seen.append(args[-1]) or True)
    monkeypatch.setattr(bridge, "_setup_superpowers_skills", lambda workspace: None)

    result = CliRunner().invoke(bridge.unreal_run, [
        "--stdin-file", str(queue),
        "--session-id", SESSION,
        "--session-directory", str(tmp_path / "sessions"),
        "--stdin-offset", str(len(first.encode("utf-8"))),
        "--idle-timeout", "5",
    ])

    assert result.exit_code == 0, result.output
    assert seen == ["nova"]


def test_skills_are_published_and_kept_out_of_git(tmp_path, monkeypatch):
    skills = tmp_path / "opt" / "skills" / "brainstorming"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: brainstorming\n---\n", encoding="utf-8")
    workspace = tmp_path / "repo"
    (workspace / ".git" / "info").mkdir(parents=True)
    monkeypatch.setattr(bridge, "SKILLS_SOURCE", str(tmp_path / "opt" / "skills"))

    bridge._setup_superpowers_skills(str(workspace))
    bridge._setup_superpowers_skills(str(workspace))

    assert (workspace / ".harness" / "skills" / "brainstorming" / "SKILL.md").exists()
    exclude = (workspace / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert exclude.splitlines().count("/.harness/") == 1


def test_unreal_model_drops_the_maki_provider_prefix(monkeypatch):
    monkeypatch.delenv("PAINKILLER_UNREAL_MODEL", raising=False)
    assert unreal_model() == "deepseek-v4-pro"
    assert unreal_model("deepseek/deepseek-flash") == "deepseek-flash"
    assert unreal_model("deepseek-flash") == "deepseek-flash"


# ---- DockerAgentSession & DockerSandboxRunner -------------------------------

@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-global")
    for name in ("PAINKILLER_CONTAINER_ROOT", "PAINKILLER_HOST_ROOT", "PAINKILLER_UNREAL_MODEL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client():
    fake = MagicMock()
    fake.containers.run.return_value = MagicMock()
    return fake


async def test_start_runs_unreal_bridge(tmp_path, client, env):
    from painkiller.adapters.sandbox.docker_agent_session import DockerAgentSession

    session = DockerAgentSession(client=client)
    await session.start(
        "analysis-unreal", str(tmp_path), "Comece", claude_session_id=SESSION,
        harness="unreal_superpowers", api_key="sk-project", model="deepseek/deepseek-v4-pro",
    )

    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["image"] == "painkiller-agent-unreal:latest"
    command = kwargs["command"]
    assert command[:2] == ["painkiller", "unreal-run"]
    assert command[command.index("--session-id") + 1] == SESSION
    assert "--stdin-offset" not in command
    environment = kwargs["environment"]
    assert environment["DEEPSEEK_API_KEY"] == "sk-project"
    assert environment["UNREAL_HARNESS_LLM_API_KEY"] == "sk-project"
    assert environment["UNREAL_HARNESS_LLM_PROVIDER"] == "openai"
    assert environment["UNREAL_HARNESS_LLM_BASE_URL"] == "https://api.deepseek.com"
    assert environment["UNREAL_HARNESS_LLM_MODEL"] == "deepseek-v4-pro"
    binds = {v["bind"] for v in kwargs["volumes"].values()}
    assert binds == {"/workspace", "/root/.local/state/unreal-agent"}


async def test_resume_skips_the_answered_queue(tmp_path, client, env):
    from painkiller.adapters.sandbox.docker_agent_session import DockerAgentSession

    queue = tmp_path / ".painkiller" / "agent-stdin.jsonl"
    queue.parent.mkdir(parents=True)
    queue.write_text('{"type": "user", "message": {"content": "Oi"}}\n', encoding="utf-8")

    session = DockerAgentSession(client=client)
    await session.start(
        "analysis-unreal", str(tmp_path), claude_session_id=SESSION, resume=True,
        harness="unreal_superpowers", api_key="sk-project",
    )

    command = client.containers.run.call_args.kwargs["command"]
    assert "--resume" not in command
    assert command[command.index("--stdin-offset") + 1] == str(os.path.getsize(queue))
    # O comando precisa ser aceito pela CLI (antes, flags desconhecidas derrubavam o contêiner).
    parsed = bridge.unreal_run.make_context("unreal-run", command[2:])
    assert parsed.params["stdin_offset"] == os.path.getsize(queue)


async def test_runner_runs_unreal_bridge_one_shot(tmp_path, env):
    from painkiller.adapters.sandbox.docker_runner import DockerSandboxRunner
    from painkiller.core.domain.models import Task, TaskStatus

    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.logs.return_value = [b'{"event": "result", "result": {"response": "ok"}}\n']
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_client.containers.run.return_value = mock_container

    runner = DockerSandboxRunner(client=mock_client)
    task = Task(id="t-unreal", project_id="p1", title="T", description="d", status=TaskStatus.READY)

    res = await runner.run_task(
        task=task,
        repo_path=str(tmp_path),
        task_instructions="Execute tests",
        harness="unreal_superpowers",
        api_key="sk-project",
    )

    assert res.exit_code == 0
    call_args = mock_client.containers.run.call_args
    assert call_args[0][0] == "painkiller-worker-unreal:latest"
    assert call_args[1]["command"] == ["painkiller", "unreal-run", "--prompt", "Execute tests"]
    environment = call_args[1]["environment"]
    assert environment["UNREAL_HARNESS_LLM_API_KEY"] == "sk-project"
    assert environment["UNREAL_HARNESS_LLM_MODEL"] == "deepseek-v4-pro"
