"""Unit tests for the Unreal Agent harness."""

import json
from unittest.mock import MagicMock
import pytest

from painkiller.cli.unreal_run import parse_unreal_line
from painkiller.core.domain.models import AgentEventType

SESSION = "12345678-1234-4234-8234-123456789012"


def test_parse_unreal_model_response():
    line = json.dumps({
        "Sequence": 1,
        "Kind": "model_response",
        "Data": {
            "TurnID": "turn-1",
            "Response": {
                "Output": [
                    {
                        "Type": "message",
                        "Data": {
                            "Role": "assistant",
                            "Text": "Olá! Sou o Unreal Agent.",
                        }
                    }
                ],
                "Usage": {
                    "InputTokens": 120,
                    "OutputTokens": 45,
                }
            }
        }
    })
    events = parse_unreal_line(line)
    assert len(events) == 2
    assert events[0].type == AgentEventType.ASSISTANT
    assert events[0].text == "Olá! Sou o Unreal Agent."
    assert events[1].type == AgentEventType.RESULT
    assert events[1].text == "Olá! Sou o Unreal Agent."


def test_parse_unreal_tool_call():
    line = json.dumps({
        "Sequence": 2,
        "Kind": "model_response",
        "Data": {
            "TurnID": "turn-1",
            "Response": {
                "Output": [
                    {
                        "Type": "tool_call",
                        "Data": {
                            "CallID": "call-1",
                            "Name": "bash",
                            "Arguments": "pytest",
                        }
                    }
                ]
            }
        }
    })
    events = parse_unreal_line(line)
    assert len(events) == 1
    assert events[0].type == AgentEventType.TOOL_USE
    assert events[0].text == "bash"


def test_parse_unreal_tool_status():
    line = json.dumps({
        "Sequence": 3,
        "Kind": "tool_call_status",
        "Data": {
            "TurnID": "turn-1",
            "CallID": "call-1",
            "Status": {"Error": ""},
            "Operations": [{"ID": "op-1", "Status": "completed"}]
        }
    })
    events = parse_unreal_line(line)
    assert len(events) == 1
    assert events[0].type == AgentEventType.TOOL_RESULT


def test_parse_unreal_error_event():
    line = json.dumps({
        "type": "error",
        "message": "authentication failed: invalid API key",
    })
    events = parse_unreal_line(line)
    assert len(events) == 1
    assert events[0].type == AgentEventType.ERROR
    assert "authentication failed" in events[0].text


# ---- DockerAgentSession & DockerSandboxRunner -------------------------------

@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-global")
    for name in ("PAINKILLER_CONTAINER_ROOT", "PAINKILLER_HOST_ROOT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client():
    fake = MagicMock()
    fake.containers.run.return_value = MagicMock()
    return fake


async def test_start_runs_unreal_in_session_mode(tmp_path, client):
    from painkiller.adapters.sandbox.docker_agent_session import DockerAgentSession

    session = DockerAgentSession(client=client)
    await session.start(
        "analysis-unreal", str(tmp_path), "Comece", claude_session_id=SESSION,
        harness="unreal_superpowers", api_key="sk-project",
    )

    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["image"] == "painkiller-agent-unreal:latest"
    command = kwargs["command"]
    assert command[:2] == ["painkiller", "unreal-run"]
    assert kwargs["environment"]["DEEPSEEK_API_KEY"] == "sk-project"
    assert kwargs["environment"]["UNREAL_HARNESS_LLM_PROVIDER"] == "openai"
    assert kwargs["environment"]["UNREAL_HARNESS_LLM_BASE_URL"] == "https://api.deepseek.com"
    binds = {v["bind"] for v in kwargs["volumes"].values()}
    assert binds == {"/workspace", "/root/.local/state/unreal-agent"}


async def test_runner_runs_unreal_one_shot(tmp_path):
    from painkiller.adapters.sandbox.docker_runner import DockerSandboxRunner
    from painkiller.core.domain.models import Task, TaskStatus

    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.logs.return_value = [b'{"type": "result", "result": "ok"}\n']
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

    mock_client.containers.run.assert_called_once()
    call_args = mock_client.containers.run.call_args
    assert call_args[0][0] == "painkiller-worker-unreal:latest"
    assert call_args[1]["command"] == [
        "unreal-agent-runner",
        "-workspace",
        "/workspace",
        "-p",
        "Execute tests",
    ]
    assert call_args[1]["environment"]["DEEPSEEK_API_KEY"] == "sk-project"
    assert call_args[1]["environment"]["UNREAL_HARNESS_LLM_PROVIDER"] == "openai"
    assert call_args[1]["environment"]["UNREAL_HARNESS_LLM_BASE_URL"] == "https://api.deepseek.com"
