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

NVIDIA_API_BASE = "https://integrate.api.nvidia.com/v1"


def resolve_aider_model(env_vars: dict[str, str]) -> Optional[str]:
    """Map Painkiller/NVIDIA variables onto what Aider reads, in place.

    O Aider só conhece OPENAI_API_KEY / OPENAI_API_BASE para endpoints
    compatíveis com OpenAI. Uma chave da NVIDIA sem base explícita ia parar
    em api.openai.com; e um modelo sem prefixo de provedor (`moonshotai/...`)
    é interpretado pelo LiteLLM como provedor desconhecido. Devolve o nome do
    modelo já com o prefixo `openai/` quando há endpoint customizado.
    """
    if "PAINKILLER_LLM_API_KEY" in env_vars and "OPENAI_API_KEY" not in env_vars:
        env_vars["OPENAI_API_KEY"] = env_vars["PAINKILLER_LLM_API_KEY"]
    if "PAINKILLER_LLM_API_BASE" in env_vars and "OPENAI_API_BASE" not in env_vars:
        env_vars["OPENAI_API_BASE"] = env_vars["PAINKILLER_LLM_API_BASE"]

    nvidia_key = env_vars.get("NVIDIA_API_KEY")
    if nvidia_key and "OPENAI_API_KEY" not in env_vars:
        env_vars["OPENAI_API_KEY"] = nvidia_key
    key = env_vars.get("OPENAI_API_KEY", "")
    if key.startswith("nvapi-") and "OPENAI_API_BASE" not in env_vars:
        env_vars["OPENAI_API_BASE"] = NVIDIA_API_BASE

    model = (env_vars.get("PAINKILLER_LLM_MODEL") or "").strip()
    if not model:
        return None
    custom_base = bool(env_vars.get("OPENAI_API_BASE"))
    known_prefixes = ("openai/", "anthropic/", "gemini/", "deepseek/", "nvidia_nim/", "ollama/")
    if custom_base and not model.startswith(known_prefixes):
        model = f"openai/{model}"
    return model


class DockerSandboxRunner(SandboxPort):
    """Executes tasks in ephemeral Docker containers running Aider and the test suite."""

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
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY",
            "DEEPSEEK_API_KEY",
            "NVIDIA_API_KEY",
            "OPENAI_API_BASE",
            "PAINKILLER_LLM_MODEL",
            "PAINKILLER_LLM_API_BASE",
            "PAINKILLER_LLM_API_KEY",
            "PAINKILLER_WORKSPACE",
        ]:
            if key in os.environ:
                env_vars[key] = os.environ[key]
        env_vars["PAINKILLER_WORKSPACE"] = "/workspace"

        command = [
            "aider",
            "--message",
            task_instructions,
            "--yes",
            "--no-check-update",
        ]
        model = resolve_aider_model(env_vars)
        if model:
            command.extend(["--model", model])

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
            if exit_code == 42:
                clarification = self._extract_clarification(repo_path, task.id)
            # O arquivo é consumido aqui: um pedido antigo não pode ser relido
            # como se fosse novo na próxima execução da mesma tarefa.
            self._discard_clarification_file(repo_path)

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

    @staticmethod
    def _discard_clarification_file(repo_path: str) -> None:
        clar_file = os.path.join(repo_path, ".painkiller", "clarification.json")
        try:
            if os.path.exists(clar_file):
                os.remove(clar_file)
        except OSError:
            pass

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
