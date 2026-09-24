"""Tests for DockerSandboxRunner harness selection and environment configuration."""

import threading
from unittest.mock import MagicMock
import pytest
from painkiller.adapters.sandbox.docker_runner import DockerSandboxRunner
from painkiller.core.domain.models import Task, TaskStatus


@pytest.mark.asyncio
async def test_docker_runner_runs_agy_by_default():
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.logs.return_value = [b'{"event": "result", "result": {"response": "ok"}}\n']
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_client.containers.run.return_value = mock_container

    runner = DockerSandboxRunner(client=mock_client)
    task = Task(id="t1", project_id="p1", title="Task 1", description="desc", status=TaskStatus.READY)

    res = await runner.run_task(
        task=task,
        repo_path="/fake/repo",
        task_instructions="Fix issue",
        harness="agy_superpowers",
        api_key="gemini-key-123",
    )

    assert res.exit_code == 0
    mock_client.containers.run.assert_called_once()
    call_args = mock_client.containers.run.call_args
    assert call_args[0][0] == "painkiller-worker:latest"
    command = call_args[1]["command"]
    assert command[0] == "agy"
    assert command[-1] == "Fix issue"
    env = call_args[1]["environment"]
    assert env["GEMINI_API_KEY"] == "gemini-key-123"


@pytest.mark.asyncio
async def test_docker_runner_runs_dsh_for_deepseek():
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.logs.return_value = [b'{"type": "result", "content": "done"}\n']
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_client.containers.run.return_value = mock_container

    runner = DockerSandboxRunner(client=mock_client)
    task = Task(id="t2", project_id="p1", title="Task 2", description="desc", status=TaskStatus.READY)

    res = await runner.run_task(
        task=task,
        repo_path="/fake/repo",
        task_instructions="Implement feature",
        harness="deepseek_superpowers",
        api_key="deepseek-key-456",
    )

    assert res.exit_code == 0
    mock_client.containers.run.assert_called_once()
    call_args = mock_client.containers.run.call_args
    assert call_args[0][0] == "painkiller-worker-deepseek:latest"
    command = call_args[1]["command"]
    assert command == ["painkiller", "acp-run", "--prompt", "Implement feature"]
    env = call_args[1]["environment"]
    assert env["DEEPSEEK_API_KEY"] == "deepseek-key-456"


def test_failure_summary_prefers_agent_last_words_over_raw_log():
    logs = "\n".join(
        [
            '{"type":"system","subtype":"init"}',
            '{"type":"assistant","message":{"content":[{"type":"text","text":"Primeira fala."}]}}',
            '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"bash","input":{"command":"ls"}}]}}',
            '{"type":"user","message":{"content":[{"type":"tool_result","content":"' + "x" * 5000 + '"}]}}',
            '{"type":"assistant","message":{"content":[{"type":"text","text":"Investigando o SyntaxError."}]}}',
        ]
    )
    assert DockerSandboxRunner._failure_summary(logs) == "Investigando o SyntaxError."


def test_failure_summary_surfaces_harness_error():
    logs = '{"type":"result","is_error":true,"result":"401 invalid api key"}\n'
    assert "chave de API" in DockerSandboxRunner._failure_summary(logs)


@pytest.mark.asyncio
async def test_docker_runner_flags_timeout():
    mock_client = MagicMock()
    mock_container = MagicMock()
    line = b'{"type":"assistant","message":{"content":[{"type":"text","text":"ainda trabalhando"}]}}\n'
    fired = threading.Event()
    # O kill do timer é o que encerra o log, como no contêiner real.
    mock_container.kill.side_effect = fired.set

    def follow(**_):
        yield line
        fired.wait(5)

    mock_container.logs.side_effect = follow
    mock_container.wait.return_value = {"StatusCode": 137}
    mock_client.containers.run.return_value = mock_container

    runner = DockerSandboxRunner(client=mock_client)
    task = Task(id="t1", project_id="p1", title="T", description="d", status=TaskStatus.READY)
    res = await runner.run_task(task=task, repo_path="/fake/repo", task_instructions="x", timeout_seconds=0.05)

    assert res.exit_code == 137
    assert res.timed_out is True
    assert res.summary == "ainda trabalhando"


@pytest.mark.asyncio
async def test_task_run_uses_the_project_model_and_effort(monkeypatch):
    monkeypatch.setenv("PAINKILLER_AGENT_MODEL", "from-env")
    monkeypatch.setenv("PAINKILLER_AGENT_EFFORT", "low")
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.logs.return_value = [b'{"event": "result", "result": {"response": "ok"}}\n']
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_client.containers.run.return_value = mock_container
    runner = DockerSandboxRunner(client=mock_client)
    task = Task(id="t3", project_id="p1", title="T", description="d", status=TaskStatus.READY)

    await runner.run_task(task=task, repo_path="/fake/repo", task_instructions="x",
                          harness="agy_superpowers", api_key="k", model="gemini-3.8-pro", effort="high")
    command = mock_client.containers.run.call_args[1]["command"]
    assert command[command.index("--model") + 1] == "gemini-3.8-pro"
    assert command[command.index("--effort") + 1] == "high"

    await runner.run_task(task=task, repo_path="/fake/repo", task_instructions="x",
                          harness="deepseek_superpowers", api_key="k", effort="high")
    env = mock_client.containers.run.call_args[1]["environment"]
    assert env["PAINKILLER_DEEPSEEK_MODEL"] == "deepseek-v4-pro"
    assert env["PAINKILLER_DEEPSEEK_EFFORT"] == "high"
