"""Tests for DockerSandboxRunner harness selection and environment configuration."""

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
    assert command == ["dsh", "--profile", "headless", "--json", "Implement feature"]
    env = call_args[1]["environment"]
    assert env["DEEPSEEK_API_KEY"] == "deepseek-key-456"
