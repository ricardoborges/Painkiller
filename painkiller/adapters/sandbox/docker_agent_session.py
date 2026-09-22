"""Docker adapter for interactive agent sessions (Antigravity CLI + Superpowers)."""

import asyncio
import json
import logging
import os
import uuid
from typing import Any, AsyncIterator, Optional

import docker

from painkiller.core.domain.models import AgentEvent, AgentEventType
from painkiller.core.ports.agent_session import AgentSessionPort
from painkiller.adapters.sandbox.paths import daemon_path

logger = logging.getLogger(__name__)

#: Caminho, dentro do contêiner, da fila que a ponte (painkiller agent-run) lê.
STDIN_RELATIVE = ".painkiller/agent-stdin.jsonl"
EOF_SENTINEL = "__painkiller_eof__"

#: Variáveis repassadas ao contêiner. O Antigravity CLI autentica via GEMINI_API_KEY
#: (ou GOOGLE_API_KEY). Variáveis legadas da Anthropic são mantidas para retrocompatibilidade.
FORWARDED_ENV = [
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "DEEPSEEK_API_KEY",
    "PAINKILLER_AGENT_MODEL",
    "PAINKILLER_AGENT_EFFORT",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_CUSTOM_MODEL_OPTION",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "AWS_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
]


class DockerAgentSession(AgentSessionPort):
    """Runs Antigravity CLI inside a container, kept alive for a back-and-forth interview."""

    def __init__(
        self,
        image_name: str = "painkiller-agent:latest",
        client: Optional[Any] = None,
        plugin_dir: str = "/opt/superpowers",
        model: Optional[str] = None,
        effort: Optional[str] = None,
        network: Optional[str] = None,
    ):
        self.image_name = image_name
        self.plugin_dir = plugin_dir
        self.model = model or os.environ.get("PAINKILLER_AGENT_MODEL") or "gemini-3.8-flash"
        self.effort = effort or os.environ.get("PAINKILLER_AGENT_EFFORT") or "medium"
        self.network = network or os.environ.get("PAINKILLER_AGENT_NETWORK") or None
        self._client = client
        self._containers: dict[str, Any] = {}
        self._stdin_files: dict[str, str] = {}

    @property
    def client(self):
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    # ---- ciclo de vida -------------------------------------------------

    async def start(
        self,
        session_id: str,
        repo_path: str,
        prompt: str = "",
        env: Optional[dict[str, str]] = None,
        timeout_seconds: int = 3600,
        resume: bool = False,
        claude_session_id: Optional[str] = None,
        harness: Optional[Any] = "agy_superpowers",
        api_key: Optional[str] = None,
    ) -> str:
        harness_type = getattr(harness, "value", harness) or "agy_superpowers"
        env_vars = {k: os.environ[k] for k in FORWARDED_ENV if k in os.environ}
        env_vars.update(env or {})
        if api_key:
            if harness_type == "deepseek_superpowers":
                env_vars["DEEPSEEK_API_KEY"] = api_key
            else:
                env_vars["GEMINI_API_KEY"] = api_key
        self._require_credentials(env_vars, harness=harness_type)

        # Pasta para persistir configurações e memória do Antigravity CLI
        gemini_home = os.path.join(repo_path, ".painkiller", "gemini_home")
        if harness_type != "deepseek_superpowers":
            os.makedirs(gemini_home, exist_ok=True)
            settings_file = os.path.join(gemini_home, "antigravity-cli", "settings.json")
            try:
                os.makedirs(os.path.dirname(settings_file), exist_ok=True)
                settings_data = {}
                if os.path.exists(settings_file):
                    try:
                        with open(settings_file, "r", encoding="utf-8") as f:
                            settings_data = json.load(f)
                    except Exception:
                        settings_data = {}
                if settings_data.get("modelProvider") != "gemini":
                    settings_data["modelProvider"] = "gemini"
                    with open(settings_file, "w", encoding="utf-8") as f:
                        json.dump(settings_data, f, indent=2)
            except Exception:
                pass

        # A fila é criada no lado da API, pelo caminho local; o contêiner a
        # enxerga através do bind mount, que o daemon resolve por outro caminho.
        stdin_path = os.path.join(repo_path, ".painkiller", "agent-stdin.jsonl")
        os.makedirs(os.path.dirname(stdin_path), exist_ok=True)
        if not resume or not os.path.exists(stdin_path):
            with open(stdin_path, "w", encoding="utf-8"):
                pass
        self._stdin_files[session_id] = stdin_path

        if harness_type == "deepseek_superpowers":
            image = os.environ.get("PAINKILLER_AGENT_DEEPSEEK_IMAGE") or "painkiller-agent-deepseek:latest"
            command = [
                "painkiller", "agent-run",
                "--agent-bin", "dsh",
                "--stdin-file", "/workspace/" + STDIN_RELATIVE,
                "--idle-timeout", str(timeout_seconds),
                "--", "--profile", "headless", "--json",
            ]
            volumes = {
                daemon_path(repo_path): {"bind": "/workspace", "mode": "rw"},
            }
        else:
            image = self.image_name
            agent_args = [
                "--model", self.model,
                "--effort", self.effort,
                "--dangerously-skip-permissions",
                "--input-format", "stream-json",
                "--output-format", "stream-json",
            ]

            if resume:
                if claude_session_id:
                    agent_args.extend(["--conversation", claude_session_id])
                else:
                    agent_args.append("--continue")

            command = [
                "painkiller", "agent-run",
                "--agent-bin", "agy",
                "--stdin-file", "/workspace/" + STDIN_RELATIVE,
                "--idle-timeout", str(timeout_seconds),
                "--", *agent_args,
            ]
            volumes = {
                daemon_path(repo_path): {"bind": "/workspace", "mode": "rw"},
                daemon_path(gemini_home): {"bind": "/root/.gemini", "mode": "rw"},
            }

        container_name = f"pk-analysis-{session_id}-{uuid.uuid4().hex[:6]}"
        loop = asyncio.get_running_loop()
        container = await loop.run_in_executor(
            None,
            lambda: self.client.containers.run(
                image=image,
                command=command,
                name=container_name,
                volumes=volumes,
                environment=env_vars,
                working_dir="/workspace",
                network=self.network,
                extra_hosts={"host.docker.internal": "host-gateway"},
                detach=True,
                remove=False,
            ),
        )
        self._containers[session_id] = container

        # O prompt inicial entra pela mesma fila: só envia se for nova sessão
        if not resume and prompt:
            await self.send(session_id, prompt)
        return container_name

    @staticmethod
    def _require_credentials(env_vars: dict[str, str], harness: str = "agy_superpowers") -> None:
        """Fail early and in pt-BR rather than letting the container die silently."""
        if harness == "deepseek_superpowers":
            if not env_vars.get("DEEPSEEK_API_KEY"):
                raise RuntimeError(
                    "DEEPSEEK_API_KEY não está definida para este projeto e nem no arquivo .env. "
                    "Configure a chave de API da DeepSeek antes de iniciar a análise."
                )
            return

        has_gemini = any(env_vars.get(k) for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"))
        has_anthropic = any(env_vars.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))
        has_cloud = any(env_vars.get(k) for k in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"))
        if has_gemini or has_anthropic or has_cloud:
            return
        raise RuntimeError(
            "GEMINI_API_KEY não está definida. O agente de análise utiliza o Antigravity CLI com o "
            "modelo Gemini 3.8 Flash. Defina GEMINI_API_KEY no arquivo .env antes de iniciar a análise."
        )

    async def send(self, session_id: str, text: str) -> None:
        await self._append(
            session_id,
            {"event": "user", "type": "user", "message": {"role": "user", "content": text}}
        )

    async def close_input(self, session_id: str) -> None:
        await self._append(session_id, {"type": EOF_SENTINEL})

    async def _append(self, session_id: str, payload: dict) -> None:
        stdin_path = self._stdin_files.get(session_id)
        if not stdin_path:
            raise ValueError(f"Sessão {session_id} não está ativa")
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._append_sync, stdin_path, line)

    @staticmethod
    def _append_sync(path: str, line: str) -> None:
        # fsync porque a ponte do outro lado do bind mount faz polling por
        # tamanho de arquivo: sem o flush ao disco ela não veria a linha.
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    async def stop(self, session_id: str) -> None:
        container = self._containers.pop(session_id, None)
        self._stdin_files.pop(session_id, None)
        loop = asyncio.get_running_loop()
        if not container:
            try:
                candidates = await loop.run_in_executor(
                    None,
                    lambda: self.client.containers.list(
                        all=True, filters={"name": f"pk-analysis-{session_id}"}
                    ),
                )
                if candidates:
                    container = candidates[0]
            except Exception:
                pass
        if not container:
            return
        await loop.run_in_executor(None, self._stop_sync, container)

    async def stop_all(self) -> None:
        """Encerra e remove todos os contêineres gerenciados."""
        session_ids = list(self._containers.keys())
        for session_id in session_ids:
            try:
                await self.stop(session_id)
            except Exception as e:
                logger.warning(f"Erro ao parar contêiner da sessão {session_id}: {e}")

    async def cleanup_orphaned_containers(
        self, active_session_ids: Optional[set[str]] = None
    ) -> list[str]:
        """Encerra e remove contêineres pk-analysis-* órfãos ou finalizados."""
        loop = asyncio.get_running_loop()
        cleaned = []
        try:
            containers = await loop.run_in_executor(
                None,
                lambda: self.client.containers.list(
                    all=True, filters={"name": "pk-analysis-"}
                ),
            )
            for c in containers:
                name = c.name or ""
                status = getattr(c, "status", "")
                should_remove = False

                if status in ("exited", "dead"):
                    should_remove = True
                elif active_session_ids is not None:
                    # Se não pertence a nenhuma sessão ativa informada, é órfão
                    is_active = any(f"pk-analysis-{sid}" in name for sid in active_session_ids)
                    if not is_active:
                        should_remove = True

                if should_remove:
                    logger.info(f"Removendo contêiner órfão de análise: {name} (status={status})")
                    await loop.run_in_executor(None, self._stop_sync, c)
                    cleaned.append(name)
        except Exception as e:
            logger.warning(f"Falha ao limpar contêineres órfãos de análise: {e}")
        return cleaned

    @staticmethod
    def _stop_sync(container: Any) -> None:
        try:
            container.kill()
        except Exception:
            pass
        try:
            container.remove(force=True)
        except Exception:
            pass

    def register_stdin_file(self, session_id: str, repo_path: str) -> None:
        self._stdin_files[session_id] = os.path.join(repo_path, ".painkiller", "agent-stdin.jsonl")

    async def is_alive(self, session_id: str) -> bool:
        container = self._containers.get(session_id)
        loop = asyncio.get_running_loop()
        if not container:
            try:
                candidates = await loop.run_in_executor(
                    None,
                    lambda: self.client.containers.list(
                        all=True, filters={"name": f"pk-analysis-{session_id}"}
                    ),
                )
                if candidates:
                    container = candidates[0]
                    self._containers[session_id] = container
                else:
                    return False
            except Exception:
                return False

        try:
            status = await loop.run_in_executor(
                None, lambda: (container.reload(), container.status)[1]
            )
            return status in ("running", "restarting")
        except Exception:
            return False

    # ---- streaming -----------------------------------------------------

    async def stream(self, session_id: str) -> AsyncIterator[AgentEvent]:
        """Yield parsed agent events until the container exits."""
        container = self._containers.get(session_id)
        loop = asyncio.get_running_loop()
        if not container:
            try:
                candidates = await loop.run_in_executor(
                    None,
                    lambda: self.client.containers.list(
                        all=True, filters={"name": f"pk-analysis-{session_id}"}
                    ),
                )
                if candidates:
                    container = candidates[0]
                    self._containers[session_id] = container
            except Exception:
                pass

        if not container:
            raise ValueError(f"Sessão {session_id} não está ativa")

        logs = container.logs(stream=True, follow=True, stdout=True, stderr=True)
        buffer = b""

        while True:
            # `logs` é um gerador bloqueante do docker-py: cada chunk é puxado
            # numa thread para não travar o event loop.
            chunk = await loop.run_in_executor(None, next, logs, None)
            if chunk is None:
                break
            buffer += chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8")
            # Um chunk não vem alinhado por linha; só linhas fechadas viram evento.
            while b"\n" in buffer:
                raw_line, buffer = buffer.split(b"\n", 1)
                event = parse_agent_line(raw_line.decode("utf-8", errors="replace").strip())
                if event:
                    yield event

        if buffer.strip():
            event = parse_agent_line(buffer.decode("utf-8", errors="replace").strip())
            if event:
                yield event

        exit_code = await loop.run_in_executor(None, lambda: container.wait().get("StatusCode", 1))
        yield AgentEvent(type=AgentEventType.EXIT, text=str(exit_code), raw={"exit_code": exit_code})


def parse_agent_line(line: str) -> Optional[AgentEvent]:
    """Map one stream-json line from Antigravity CLI or Claude Code onto a domain event."""
    if not line:
        return None
    try:
        data = json.loads(line)
    except ValueError:
        # Ruído de stderr não é fatal.
        return AgentEvent(type=AgentEventType.ERROR, text=line, raw={"line": line})

    # Eventos nativos do Antigravity CLI (`agy`)
    if "event" in data:
        evt = data.get("event")
        if evt == "init":
            init_data = data.get("init") or {}
            model = init_data.get("model", "gemini-3.8-flash")
            return AgentEvent(type=AgentEventType.SYSTEM, text=f"Iniciando agente com {model}", raw=data)
        if evt == "step_update":
            step = data.get("step_update") or {}
            step_type = step.get("step_type")
            if step_type == "agent_response":
                if "text_delta" in step:
                    return AgentEvent(type=AgentEventType.ASSISTANT_DELTA, text=step["text_delta"], raw=data)
                if "thinking_delta" in step:
                    return AgentEvent(type=AgentEventType.THINKING_DELTA, text=step["thinking_delta"], raw=data)
                if step.get("state") == "DONE" and step.get("response"):
                    return AgentEvent(type=AgentEventType.ASSISTANT, text=step["response"], raw=data)
            elif step_type == "tool":
                tool_name = step.get("tool_name") or (step.get("tool_info") or {}).get("name") or ""
                state = step.get("state")
                if state in ("ACTIVE", "RUNNING"):
                    return AgentEvent(type=AgentEventType.TOOL_USE, text=tool_name, raw=data)
                return AgentEvent(type=AgentEventType.TOOL_RESULT, text=tool_name, raw=data)
            return None
        if evt == "result":
            res = data.get("result") or {}
            text = res.get("response") or ""
            return AgentEvent(type=AgentEventType.RESULT, text=text, raw=data)

    # Eventos legados do Claude Code e DeepSeek Harness (`dsh`)
    kind = data.get("type")
    if kind == "stream_event":
        return _from_stream_event(data)
    if kind == "assistant":
        return _from_assistant(data)
    if kind == "user":
        return _from_tool_result(data)
    if kind in ("result", "done"):
        text = data.get("result") or data.get("response") or data.get("text") or data.get("content") or ""
        return AgentEvent(type=AgentEventType.RESULT, text=text, raw=data)
    if kind == "system":
        return AgentEvent(type=AgentEventType.SYSTEM, text=data.get("subtype", "") or data.get("message", ""), raw=data)
    if kind in ("delta", "text_delta"):
        text = data.get("text") or data.get("delta") or data.get("content") or ""
        return AgentEvent(type=AgentEventType.ASSISTANT_DELTA, text=text, raw=data) if text else None
    if kind in ("thought", "thinking", "thinking_delta"):
        text = data.get("thinking") or data.get("thought") or data.get("text") or ""
        return AgentEvent(type=AgentEventType.THINKING_DELTA, text=text, raw=data) if text else None
    if kind in ("tool_call", "tool_use"):
        tool_name = data.get("name") or data.get("tool") or (data.get("tool_call") or {}).get("name") or ""
        return AgentEvent(type=AgentEventType.TOOL_USE, text=tool_name, raw=data)
    if kind == "tool_result":
        tool_name = data.get("name") or data.get("tool") or ""
        return AgentEvent(type=AgentEventType.TOOL_RESULT, text=tool_name, raw=data)
    return None


def _from_stream_event(data: dict) -> Optional[AgentEvent]:
    """Map an incremental chunk. Everything but visible text is ignored here."""
    event = data.get("event") or {}
    if event.get("type") != "content_block_delta":
        return None
    delta = event.get("delta") or {}
    kind = delta.get("type")
    if kind == "text_delta":
        text = delta.get("text") or ""
        return AgentEvent(type=AgentEventType.ASSISTANT_DELTA, text=text) if text else None
    if kind == "thinking_delta":
        text = delta.get("thinking") or ""
        return AgentEvent(type=AgentEventType.THINKING_DELTA, text=text) if text else None
    return None


def _from_assistant(data: dict) -> Optional[AgentEvent]:
    blocks = (data.get("message") or {}).get("content") or []
    texts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            texts.append(block.get("text", ""))
        elif block.get("type") == "thinking":
            return AgentEvent(type=AgentEventType.THINKING, text=block.get("thinking", ""), raw=data)
        elif block.get("type") == "tool_use":
            return AgentEvent(type=AgentEventType.TOOL_USE, text=block.get("name", ""), raw=data)
    joined = "".join(texts).strip()
    if not joined:
        return None
    return AgentEvent(type=AgentEventType.ASSISTANT, text=joined, raw=data)


def _from_tool_result(data: dict) -> Optional[AgentEvent]:
    blocks = (data.get("message") or {}).get("content") or []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            return AgentEvent(type=AgentEventType.TOOL_RESULT, text="", raw=data)
    return None
