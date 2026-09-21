"""Tests for DockerSandboxRunner with mocked and real Docker engine."""

import json
import os
import tempfile
from unittest.mock import MagicMock
import pytest
from painkiller.core.domain.models import Task, TaskStatus
from painkiller.adapters.sandbox.docker_runner import DockerSandboxRunner


@pytest.mark.asyncio
async def test_docker_runner_clarification_exit_42():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a mock clarification.json in tmpdir/.painkiller
        pk_dir = os.path.join(tmpdir, ".painkiller")
        os.makedirs(pk_dir, exist_ok=True)
        with open(os.path.join(pk_dir, "clarification.json"), "w", encoding="utf-8") as f:
            json.dump({
                "question": "Which database library?",
                "context_summary": "db.py line 10",
                "timestamp": "2026-09-19T21:45:00Z"
            }, f)

        # Mock docker container and client
        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 42}
        mock_container.logs.return_value = b"Starting agy...\nExiting for clarification (exit 42)\n"

        mock_docker_client = MagicMock()
        mock_docker_client.containers.run.return_value = mock_container

        runner = DockerSandboxRunner(client=mock_docker_client)

        task = Task(
            id="task-mock-1",
            project_id="proj-1",
            title="Setup DB",
            description="Setup DB schema",
        )

        result = await runner.run_task(
            task=task,
            repo_path=tmpdir,
            task_instructions="Setup DB schema",
            timeout_seconds=30,
        )

        assert result.exit_code == 42
        assert result.clarification is not None
        assert result.clarification.question == "Which database library?"
        assert result.clarification.context_summary == "db.py line 10"
        cmd = mock_docker_client.containers.run.call_args.kwargs["command"]
        assert cmd[0] == "agy"
        assert "--print" in cmd
        assert "--output-format" in cmd and "stream-json" in cmd


@pytest.mark.asyncio
async def test_docker_runner_success_exit_0():
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.return_value = b'{"event": "result", "result": {"response": "Task completed successfully."}}\n'

        mock_docker_client = MagicMock()
        mock_docker_client.containers.run.return_value = mock_container

        runner = DockerSandboxRunner(client=mock_docker_client)
        task = Task(id="task-mock-2", project_id="proj-1", title="Write test", description="Write test")

        result = await runner.run_task(
            task=task,
            repo_path=tmpdir,
            task_instructions="Write test",
            timeout_seconds=30,
        )

        assert result.exit_code == 0
        assert result.clarification is None
        assert "Task completed successfully" in result.logs
        cmd = mock_docker_client.containers.run.call_args.kwargs["command"]
        assert cmd[0] == "agy"
        assert "--print" in cmd
