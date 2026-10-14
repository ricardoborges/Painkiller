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



@pytest.mark.asyncio
async def test_docker_runner_explains_missing_worker_image():
    import docker

    mock_client = MagicMock()
    # Sem a imagem local o docker-py tenta um pull, que falha com um 404 cru.
    mock_client.containers.run.side_effect = docker.errors.ImageNotFound("pull access denied")

    runner = DockerSandboxRunner(client=mock_client)
    task = Task(id="t3", project_id="p1", title="Task 3", description="desc", status=TaskStatus.READY)

    res = await runner.run_task(
        task=task,
        repo_path="/fake/repo",
        task_instructions="Implement feature",
        harness="deepseek_superpowers",
        api_key="deepseek-key-456",
    )

    assert res.exit_code == 1
    assert "painkiller-worker-deepseek:latest" in res.summary
    assert "docker compose --profile build build" in res.summary

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


@pytest.mark.asyncio
async def test_docker_runner_mounts_per_project_package_cache():
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.logs.return_value = [b'{"event": "result", "result": {"response": "ok"}}\n']
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_client.containers.run.return_value = mock_container

    runner = DockerSandboxRunner(client=mock_client)
    task = Task(id="t1", project_id="p1", title="Task 1", description="desc", status=TaskStatus.READY)
    await runner.run_task(task=task, repo_path="/fake/repo", task_instructions="x", api_key="k")

    kwargs = mock_client.containers.run.call_args[1]
    # Volume do projeto, nunca compartilhado entre donos.
    assert kwargs["volumes"]["painkiller-cache-p1"] == {"bind": "/cache", "mode": "rw"}
    env = kwargs["environment"]
    assert env["NPM_CONFIG_CACHE"] == "/cache/npm"
    assert env["UV_CACHE_DIR"] == "/cache/uv"
    assert env["PIP_CACHE_DIR"] == "/cache/pip"


def test_remove_package_cache_is_best_effort():
    mock_client = MagicMock()
    runner = DockerSandboxRunner(client=mock_client)
    runner.remove_package_cache("p1")
    mock_client.volumes.get.assert_called_once_with("painkiller-cache-p1")

    mock_client.volumes.get.side_effect = RuntimeError("daemon fora")
    runner.remove_package_cache("p2")  # não levanta


@pytest.mark.asyncio
async def test_run_tests_runs_in_the_harness_worker_from_the_test_root(tmp_path):
    # backend/tests importa `app` de backend/: o pytest tem de rodar de lá.
    (tmp_path / "backend" / "tests").mkdir(parents=True)
    (tmp_path / "backend" / "tests" / "test_health.py").write_text("def test_ok(): pass\n")
    (tmp_path / "backend" / "requirements.txt").write_text("fastapi\n")
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.logs.return_value = [b"1 passed\n"]
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_client.containers.run.return_value = mock_container

    runner = DockerSandboxRunner(client=mock_client)
    task = Task(id="t1", project_id="p1", title="T", description="d")
    code, out = await runner.run_tests(task, str(tmp_path), harness="maki_superpowers")

    assert (code, out) == (0, "1 passed\n")
    args, kwargs = mock_client.containers.run.call_args
    assert args[0] == "painkiller-worker-maki:latest"
    script = kwargs["command"][2]
    assert "cd /workspace/backend" in script
    assert "-r requirements.txt" in script
    assert "--rootdir=." in script
    assert kwargs["name"].startswith("pk-task-t1-")
    assert "GEMINI_API_KEY" not in kwargs["environment"]
    assert "DEEPSEEK_API_KEY" not in kwargs["environment"]


@pytest.mark.asyncio
async def test_run_tests_without_python_tests_starts_no_container(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>")
    mock_client = MagicMock()
    runner = DockerSandboxRunner(client=mock_client)
    task = Task(id="t1", project_id="p1", title="T", description="d")

    code, _ = await runner.run_tests(task, str(tmp_path))

    assert code == 5
    mock_client.containers.run.assert_not_called()
