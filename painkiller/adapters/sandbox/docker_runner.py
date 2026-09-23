"""Docker Sandbox Runner implementing SandboxPort."""

import asyncio
import json
import logging
import os
import threading
import uuid
from typing import Optional, Any
import docker

from painkiller.core.domain.models import Task, ExecutionResult, ClarificationRequest
from painkiller.core.ports.sandbox import AgentEventCallback, SandboxPort
from painkiller.adapters.sandbox.docker_agent_session import maki_model, parse_agent_line
from painkiller.adapters.sandbox.paths import daemon_path

logger = logging.getLogger(__name__)


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
        on_event: Optional[AgentEventCallback] = None,
        harness: Optional[str] = None,
        api_key: Optional[str] = None,
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
            on_event,
            harness,
            api_key,
        )

    def _run_task_sync(
        self,
        task: Task,
        repo_path: str,
        task_instructions: str,
        timeout_seconds: int,
        on_event: Optional[AgentEventCallback] = None,
        harness: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> ExecutionResult:
        container_name = f"pk-task-{task.id}-{uuid.uuid4().hex[:6]}"

        # Collect API keys from current environment
        env_vars = {}
        for key in [
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "DEEPSEEK_API_KEY",
            "PAINKILLER_DEEPSEEK_MODEL",
            "PAINKILLER_DEEPSEEK_EFFORT",
            "PAINKILLER_MAKI_MODEL",
            "PAINKILLER_AGENT_MODEL",
            "PAINKILLER_AGENT_EFFORT",
            "PAINKILLER_LLM_MODEL",
            "PAINKILLER_WORKSPACE",
        ]:
            if key in os.environ:
                env_vars[key] = os.environ[key]
        env_vars["PAINKILLER_WORKSPACE"] = "/workspace"

        harness_type = getattr(harness, "value", harness) or "agy_superpowers"
        if harness_type == "maki_superpowers":
            image = os.environ.get("PAINKILLER_WORKER_MAKI_IMAGE") or "painkiller-worker-maki:latest"
            if api_key:
                env_vars["DEEPSEEK_API_KEY"] = api_key
            # Um turno só, como o `agy --print`; saída no stream-json do Claude Code.
            command = [
                "maki",
                "--trust",
                "--yolo",
                "--print",
                "--output-format",
                "stream-json",
                "--include-partial-messages",
                "--model",
                maki_model(),
                task_instructions,
            ]
        elif harness_type == "deepseek_superpowers":
            image = os.environ.get("PAINKILLER_WORKER_DEEPSEEK_IMAGE") or "painkiller-worker-deepseek:latest"
            if api_key:
                env_vars["DEEPSEEK_API_KEY"] = api_key
            # Um turno só, como o `agy --print`; a ponte emite o mesmo stream-json.
            command = [
                "painkiller",
                "acp-run",
                "--prompt",
                task_instructions,
            ]
        else:
            image = self.image_name
            if api_key:
                env_vars["GEMINI_API_KEY"] = api_key
                env_vars["GOOGLE_API_KEY"] = api_key

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
                image,
                command=command,
                name=container_name,
                volumes={self._daemon_path(repo_path): {"bind": "/workspace", "mode": "rw"}},
                environment=env_vars,
                detach=True,
                working_dir="/workspace",
                remove=False,
            )
            self._running_containers[task.id] = container

            # Seguir o log bloqueia até o contêiner sair; o timer garante que
            # um agente pendurado não segure a thread para sempre.
            timer = threading.Timer(timeout_seconds, self._kill_on_timeout, (container, task.id))
            timer.daemon = True
            timer.start()
            try:
                logs = self._follow_logs(container, on_event)
                res = container.wait()
            finally:
                timer.cancel()
            exit_code = res.get("StatusCode", 1)
            if exit_code == 0 and self._ended_in_error(logs):
                # O maki sai com 0 mesmo quando o turno falhou (chave recusada,
                # sem saldo): sem isto a tarefa seguiria para os testes e o review.
                exit_code = 1

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

    @staticmethod
    def _ended_in_error(logs: str) -> bool:
        """Whether the last stream-json `result` in the logs reports is_error."""
        for line in reversed((logs or "").splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("type") == "result":
                return bool(data.get("is_error"))
        return False

    @staticmethod
    def _kill_on_timeout(container: Any, task_id: str) -> None:
        logger.warning(f"Task {task_id} exceeded its timeout; killing container")
        try:
            container.kill()
        except Exception:
            pass

    @staticmethod
    def _follow_logs(container: Any, on_event: Optional[AgentEventCallback]) -> str:
        """Stream the container's output until it exits, returning all of it.

        Each complete line is parsed and handed to ``on_event``; a callback
        failure never interrupts the run.
        """
        chunks: list[bytes] = []
        pending = b""

        def emit(raw: bytes) -> None:
            if on_event is None:
                return
            line = raw.decode("utf-8", errors="replace").strip()
            event = parse_agent_line(line)
            if event is None:
                return
            try:
                on_event(event)
            except Exception as e:
                logger.debug(f"on_event callback failed: {e}")

        stream = container.logs(stdout=True, stderr=True, stream=True, follow=True)
        if isinstance(stream, (bytes, str)):
            stream = [stream]
        for chunk in stream:
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            chunks.append(chunk)
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                emit(line)
        if pending.strip():
            emit(pending)
        return b"".join(chunks).decode("utf-8", errors="replace")

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

    async def cleanup_orphaned_containers(self) -> list[str]:
        """Remove contêineres pk-task-* que já finalizaram ou estão mortos."""
        loop = asyncio.get_running_loop()
        cleaned = []
        try:
            containers = await loop.run_in_executor(
                None,
                lambda: self.client.containers.list(all=True, filters={"name": "pk-task-"}),
            )
            for c in containers:
                status = getattr(c, "status", "")
                if status in ("exited", "dead"):
                    try:
                        name = c.name
                        await loop.run_in_executor(None, lambda: c.remove(force=True))
                        cleaned.append(name)
                        logger.info(f"Removido contêiner de tarefa finalizado: {name}")
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Falha ao limpar contêineres órfãos de task: {e}")
        return cleaned
