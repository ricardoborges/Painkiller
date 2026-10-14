"""Docker Sandbox Runner implementing SandboxPort."""

import asyncio
import contextvars
import json
import logging
import os
import threading
import uuid
from typing import Optional, Any
import docker

from painkiller.core.domain.models import (
    AgentEventType,
    ClarificationRequest,
    ExecutionResult,
    Task,
    harness_effort,
    harness_model,
)
from painkiller.core.i18n import tr
from painkiller.core.test_plan import NO_TESTS_COLLECTED, build_test_script
from painkiller.core.ports.sandbox import AgentEventCallback, SandboxPort
from painkiller.adapters.sandbox.docker_agent_session import parse_agent_line, unreal_env
from painkiller.adapters.sandbox.paths import daemon_path

logger = logging.getLogger(__name__)

#: Onde o volume de cache de pacotes entra no worker.
PACKAGE_CACHE_MOUNT = "/cache"

#: Gerenciadores apontados para o volume: sem isto cada contêiner one-shot
#: baixava tudo de novo a cada tarefa.
PACKAGE_CACHE_ENV = {
    "NPM_CONFIG_CACHE": f"{PACKAGE_CACHE_MOUNT}/npm",
    "PIP_CACHE_DIR": f"{PACKAGE_CACHE_MOUNT}/pip",
    "UV_CACHE_DIR": f"{PACKAGE_CACHE_MOUNT}/uv",
    "PNPM_STORE_DIR": f"{PACKAGE_CACHE_MOUNT}/pnpm",
    "YARN_CACHE_FOLDER": f"{PACKAGE_CACHE_MOUNT}/yarn",
}


def package_cache_volume(project_id: str) -> str:
    """Named volume holding a project's package caches.

    Um por projeto, nunca compartilhado: o agente roda comandos à vontade, e um
    cache comum deixaria um projeto envenenar os pacotes de outro dono.
    """
    return f"painkiller-cache-{project_id}"


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

    def remove_package_cache(self, project_id: str) -> None:
        """Drop a deleted project's package cache volume; best effort."""
        try:
            self.client.volumes.get(package_cache_volume(project_id)).remove(force=True)
        except Exception as e:  # noqa: BLE001 — volume ausente ou daemon fora
            logger.debug("package cache of %s not removed: %s", project_id, e)

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
        model: Optional[str] = None,
        effort: Optional[str] = None,
    ) -> ExecutionResult:
        """Run the task in a detached Docker container, waiting for completion or clarification."""
        loop = asyncio.get_running_loop()
        # O executor não herda o contexto: sem a cópia, as mensagens que a
        # thread escreve para o analista sairiam no idioma padrão, não no do projeto.
        context = contextvars.copy_context()
        return await loop.run_in_executor(
            None,
            context.run,
            self._run_task_sync,
            task,
            repo_path,
            task_instructions,
            timeout_seconds,
            on_event,
            harness,
            api_key,
            model,
            effort,
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
        model: Optional[str] = None,
        effort: Optional[str] = None,
    ) -> ExecutionResult:
        container_name = f"pk-task-{task.id}-{uuid.uuid4().hex[:6]}"

        # Chave, modelo e esforço vêm só do projeto; nada do ambiente da API.
        env_vars = {"PAINKILLER_WORKSPACE": "/workspace", **PACKAGE_CACHE_ENV}

        harness_type = getattr(harness, "value", harness) or "agy_superpowers"
        image = self._worker_image(harness_type)
        if harness_type == "maki_superpowers":
            env_vars["DEEPSEEK_API_KEY"] = api_key or ""
            chosen_model = harness_model(harness_type, model)
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
                chosen_model,
                task_instructions,
            ]
        elif harness_type == "deepseek_superpowers":
            env_vars["DEEPSEEK_API_KEY"] = api_key or ""
            # A ponte aplica os dois via session/set_config_option.
            env_vars["PAINKILLER_DEEPSEEK_MODEL"] = harness_model(harness_type, model)
            env_vars["PAINKILLER_DEEPSEEK_EFFORT"] = harness_effort(harness_type, effort) or ""
            # Um turno só, como o `agy --print`; a ponte emite o mesmo stream-json.
            command = [
                "painkiller",
                "acp-run",
                "--prompt",
                task_instructions,
            ]
        elif harness_type == "unreal_superpowers":
            env_vars["DEEPSEEK_API_KEY"] = api_key or ""
            unreal_env(env_vars, model)
            # Um turno só, como o `agy --print`; a ponte publica as skills e
            # emite o mesmo stream-json.
            command = [
                "painkiller",
                "unreal-run",
                "--prompt",
                task_instructions,
            ]
        else:
            env_vars["GEMINI_API_KEY"] = api_key or ""
            env_vars["GOOGLE_API_KEY"] = api_key or ""

            chosen_model = harness_model(harness_type, model)
            effort = harness_effort(harness_type, effort)

            command = [
                "agy",
                "--model",
                chosen_model,
                "--effort",
                effort,
                "--dangerously-skip-permissions",
                "--output-format",
                "stream-json",
                "--print",
                task_instructions,
            ]

        if not task.use_superpowers:
            command = self._without_superpowers(command, env_vars)

        # Uma pergunta já respondida deixa o clarification.json no workspace.
        # A existência do arquivo conta como pausa (o `painkiller ask` sai com
        # 42 dentro da ferramenta do agente, não do contêiner), então um arquivo
        # velho faria a reexecução pausar de novo com a mesma pergunta.
        self._discard_clarification(repo_path)

        try:
            container = self.client.containers.run(
                image,
                command=command,
                name=container_name,
                volumes={
                    self._daemon_path(repo_path): {"bind": "/workspace", "mode": "rw"},
                    # Volume nomeado: o daemon cria na primeira vez, sem caminho do host.
                    package_cache_volume(task.project_id): {"bind": PACKAGE_CACHE_MOUNT, "mode": "rw"},
                },
                environment=env_vars,
                detach=True,
                working_dir="/workspace",
                remove=False,
            )
            self._running_containers[task.id] = container

            # Seguir o log bloqueia até o contêiner sair; o timer garante que
            # um agente pendurado não segure a thread para sempre.
            timed_out = threading.Event()
            timer = threading.Timer(
                timeout_seconds, self._kill_on_timeout, (container, task.id, timed_out)
            )
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
                timed_out=timed_out.is_set() and exit_code != 42,
                summary=None if exit_code in (0, 42) else self._failure_summary(logs),
            )
        except docker.errors.ImageNotFound as e:
            # Sem a imagem local, o docker-py tenta um pull do Docker Hub, que
            # falha com um 404 cru ("pull access denied"). Diz o que fazer.
            message = tr(
                "A imagem do agente '{image}' não foi encontrada no Docker. "
                "Construa as imagens dos harnesses com: docker compose --profile build build",
                image=image,
            )
            return ExecutionResult(
                exit_code=1,
                logs=f"Container execution error: {e}",
                summary=message,
            )
        except Exception as e:
            return ExecutionResult(
                exit_code=1,
                logs=f"Container execution error: {e}",
            )
        finally:
            self._cleanup_container(task.id)

    @staticmethod
    def _without_superpowers(command: list[str], env_vars: dict[str, str]) -> list[str]:
        """Run the agent with the superpowers skills out of its catalog.

        O prompt já proíbe as skills, mas um catálogo visível tenta o agente.
        O contêiner é descartável, então tirar o link do dsh/maki
        (~/.agents/skills) não toca a imagem; a ponte do unreal lê a variável
        e não publica as skills no workspace. O plugin do agy fica: removê-lo
        por fora do `agy plugin` pode quebrar a inicialização.
        """
        env_vars["PAINKILLER_SUPERPOWERS"] = "0"
        return ["sh", "-c", 'rm -f "$HOME/.agents/skills"; exec "$@"', "sh", *command]

    def _worker_image(self, harness_type: str) -> str:
        if harness_type == "maki_superpowers":
            return os.environ.get("PAINKILLER_WORKER_MAKI_IMAGE") or "painkiller-worker-maki:latest"
        if harness_type == "deepseek_superpowers":
            return os.environ.get("PAINKILLER_WORKER_DEEPSEEK_IMAGE") or "painkiller-worker-deepseek:latest"
        if harness_type == "unreal_superpowers":
            return os.environ.get("PAINKILLER_WORKER_UNREAL_IMAGE") or "painkiller-worker-unreal:latest"
        return self.image_name

    async def run_tests(
        self,
        task: Task,
        repo_path: str,
        harness: Optional[str] = None,
        timeout_seconds: int = 900,
    ) -> tuple[int, str]:
        """Run the repo's tests in a worker container, never in the API process."""
        script = build_test_script(repo_path)
        if script is None:
            return (NO_TESTS_COLLECTED, tr("(Sem testes coletados no repositório)"))
        loop = asyncio.get_running_loop()
        context = contextvars.copy_context()
        return await loop.run_in_executor(
            None, context.run, self._run_tests_sync, task, repo_path, script, harness, timeout_seconds
        )

    def _run_tests_sync(
        self,
        task: Task,
        repo_path: str,
        script: str,
        harness: Optional[str],
        timeout_seconds: int,
    ) -> tuple[int, str]:
        harness_type = getattr(harness, "value", harness) or "agy_superpowers"
        image = self._worker_image(harness_type)
        # Prefixo pk-task-{id}: o stop_task acha este contêiner pelo nome também.
        container_name = f"pk-task-{task.id}-tests-{uuid.uuid4().hex[:6]}"
        try:
            # Sem chave de API: a suíte não precisa de LLM.
            container = self.client.containers.run(
                image,
                command=["sh", "-c", script],
                name=container_name,
                volumes={
                    self._daemon_path(repo_path): {"bind": "/workspace", "mode": "rw"},
                    package_cache_volume(task.project_id): {"bind": PACKAGE_CACHE_MOUNT, "mode": "rw"},
                },
                environment={"PAINKILLER_WORKSPACE": "/workspace", **PACKAGE_CACHE_ENV},
                detach=True,
                working_dir="/workspace",
                remove=False,
            )
            self._running_containers[task.id] = container
            timer = threading.Timer(timeout_seconds, self._kill_on_timeout, (container, task.id))
            timer.daemon = True
            timer.start()
            try:
                logs = self._follow_logs(container, None)
                res = container.wait()
            finally:
                timer.cancel()
            return (res.get("StatusCode", 1), logs)
        except docker.errors.ImageNotFound:
            return (1, tr(
                "A imagem do agente '{image}' não foi encontrada no Docker. "
                "Construa as imagens dos harnesses com: docker compose --profile build build",
                image=image,
            ))
        except Exception as e:
            return (1, f"Container execution error: {e}")
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
    def _failure_summary(logs: str, limit: int = 1500) -> Optional[str]:
        """What the analyst needs from a failed run: the harness error, else the agent's last words.

        The raw log is hundreds of KB of stream-json; this keeps the error readable.
        """
        harness_error: Optional[str] = None
        last_text = ""
        partial = ""
        stderr: list[str] = []
        for raw in (logs or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            event = parse_agent_line(line)
            if event is None:
                continue
            if event.type == AgentEventType.ERROR:
                if event.raw.get("harness_error"):
                    harness_error = event.text
                elif not line.startswith("{"):
                    stderr.append(line)
            elif event.type == AgentEventType.ASSISTANT_DELTA:
                partial += event.text
            elif event.type in (AgentEventType.ASSISTANT, AgentEventType.RESULT) and event.text.strip():
                last_text = event.text
                partial = ""
            elif event.type == AgentEventType.TOOL_USE:
                if partial.strip():
                    last_text = partial
                partial = ""
        if partial.strip():
            last_text = partial

        summary = harness_error or last_text.strip() or "\n".join(stderr[-8:])
        if not summary:
            return None
        summary = summary.strip()
        if len(summary) > limit:
            summary = "…" + summary[-limit:]
        return summary

    @staticmethod
    def _kill_on_timeout(container: Any, task_id: str, flag: Optional[threading.Event] = None) -> None:
        logger.warning(f"Task {task_id} exceeded its timeout; killing container")
        if flag is not None:
            flag.set()
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

    @staticmethod
    def _discard_clarification(repo_path: str) -> None:
        clar_file = os.path.join(repo_path, ".painkiller", "clarification.json")
        try:
            os.remove(clar_file)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"Não foi possível remover {clar_file}: {e}")

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
        loop = asyncio.get_running_loop()
        container = self._running_containers.get(task_id)
        if container:
            try:
                await loop.run_in_executor(None, lambda: container.kill())
            except Exception as e:
                logger.debug(f"Falha ao matar contêiner ativo para task {task_id}: {e}")

        # Fallback: buscar e parar qualquer contêiner ativo associado a esta task
        def _stop_by_name():
            try:
                containers = self.client.containers.list(filters={"name": f"pk-task-{task_id}"})
                for c in containers:
                    try:
                        c.kill()
                    except Exception:
                        pass
            except Exception as ex:
                logger.debug(f"Falha ao buscar contêineres por nome para task {task_id}: {ex}")

        await loop.run_in_executor(None, _stop_by_name)

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
