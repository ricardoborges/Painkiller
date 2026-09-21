"""Docker Sandbox Runner implementing SandboxPort."""

import asyncio
import json
import os
import uuid
from typing import Optional, Any
import docker

from painkiller.core.domain.models import Task, ExecutionResult, ClarificationRequest
from painkiller.core.ports.sandbox import SandboxPort
from painkiller.adapters.sandbox.paths import daemon_path


class DockerSandboxRunner(SandboxPort):
    """Executes tasks in ephemeral Docker containers running Antigravity CLI (agy) and the test suite."""

    def __init__(
        self,
        image_name: str = "painkiller-worker:latest",
        client: Optional[Any] = None,
    ):
        self.image_name = image_name
        self._client = client
        self._running_containers: dict[str, Any] = {}

    @property
    def client(self):
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    # Mantido como staticmethod para nao quebrar chamadas existentes; a
    # implementacao real vive em paths.py, compartilhada com a sessao interativa.
    _daemon_path = staticmethod(daemon_path)

    async def run_task(
        self,
        task: Task,
        repo_path: str,
        task_instructions: str,
        timeout_seconds: int = 600,
    ) -> ExecutionResult:
        """Run the task in a detached Docker container, waiting for completion or clarification."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._run_task_sync,
            task,
            repo_path,
            task_instructions,
            timeout_seconds,
        )

    def _run_task_sync(
        self,
        task: Task,
        repo_path: str,
        task_instructions: str,
        timeout_seconds: int,
    ) -> ExecutionResult:
        container_name = f"pk-task-{task.id}-{uuid.uuid4().hex[:6]}"

        # Collect API keys from current environment
        env_vars = {}
        for key in [
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "PAINKILLER_AGENT_MODEL",
            "PAINKILLER_AGENT_EFFORT",
            "PAINKILLER_LLM_MODEL",
            "PAINKILLER_WORKSPACE",
        ]:
            if key in os.environ:
                env_vars[key] = os.environ[key]
        env_vars["PAINKILLER_WORKSPACE"] = "/workspace"

        model = (
            env_vars.get("PAINKILLER_AGENT_MODEL")
            or env_vars.get("PAINKILLER_LLM_MODEL")
            or "gemini-3.8-flash"
        )
        effort = env_vars.get("PAINKILLER_AGENT_EFFORT") or "medium"

        command = [
            "agy",
            "--model",
            model,
            "--effort",
            effort,
            "--dangerously-skip-permissions",
            "--output-format",
            "stream-json",
            "--print",
            task_instructions,
        ]

        try:
            container = self.client.containers.run(
                self.image_name,
                command=command,
                name=container_name,
                volumes={self._daemon_path(repo_path): {"bind": "/workspace", "mode": "rw"}},
                environment=env_vars,
                detach=True,
                working_dir="/workspace",
                remove=False,
            )
            self._running_containers[task.id] = container

            res = container.wait(timeout=timeout_seconds)
            exit_code = res.get("StatusCode", 1)
            raw_logs = container.logs(stdout=True, stderr=True)
            logs = raw_logs.decode("utf-8", errors="replace") if isinstance(raw_logs, bytes) else str(raw_logs)

            clarification = None
            clar_file = os.path.join(repo_path, ".painkiller", "clarification.json")
            if exit_code == 42 or os.path.exists(clar_file):
                clarification = self._extract_clarification(repo_path, task.id)
                if clarification:
                    exit_code = 42

            return ExecutionResult(
                exit_code=exit_code,
                logs=logs,
                clarification=clarification,
            )
        except Exception as e:
            return ExecutionResult(
                exit_code=1,
                logs=f"Container execution error: {e}",
            )
        finally:
            self._cleanup_container(task.id)

    def _extract_clarification(self, repo_path: str, task_id: str) -> Optional[ClarificationRequest]:
        clar_file = os.path.join(repo_path, ".painkiller", "clarification.json")
        if os.path.exists(clar_file):
            try:
                with open(clar_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return ClarificationRequest(
                    id=f"clar-{uuid.uuid4().hex[:8]}",
                    task_id=task_id,
                    question=data.get("question", "Clarification needed"),
                    context_summary=data.get("context_summary", ""),
                )
            except Exception:
                return None
        return None

    def _cleanup_container(self, task_id: str) -> None:
        container = self._running_containers.pop(task_id, None)
        if container:
            try:
                container.remove(force=True)
            except Exception:
                pass

    async def stop_task(self, task_id: str) -> None:
        container = self._running_containers.get(task_id)
        if container:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, container.stop)
