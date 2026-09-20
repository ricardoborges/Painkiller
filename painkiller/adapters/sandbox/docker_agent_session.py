"""Docker adapter for interactive agent sessions (Claude Code + superpowers)."""

import asyncio
import json
import os
import uuid
from typing import Any, AsyncIterator, Optional

import docker

from painkiller.core.domain.models import AgentEvent, AgentEventType
from painkiller.core.ports.agent_session import AgentSessionPort
from painkiller.adapters.sandbox.paths import daemon_path

#: Caminho, dentro do contêiner, da fila que a ponte (painkiller agent-run) lê.
STDIN_RELATIVE = ".painkiller/agent-stdin.jsonl"
EOF_SENTINEL = "__painkiller_eof__"

#: Variáveis repassadas ao contêiner. O Claude Code fala a Messages API da
#: Anthropic, então o backend precisa servir /v1/messages: ou a Anthropic
#: direto, ou um NIM auto-hospedado, ou o proxy tradutor do LiteLLM apontando
#: para o NVIDIA Build (ver docker/litellm-proxy.yaml).
FORWARDED_ENV = [
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    # Um backend próprio não atende pelos nomes de modelo da Anthropic. Sem
    # remapear os aliases embutidos, o Claude Code continua pedindo "haiku"
    # para tarefas de fundo e toma 404 — é a ressalva da documentação da NVIDIA.
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
    """Runs Claude Code inside a container, kept alive for a back-and-forth interview."""

    def __init__(
        self,
        image_name: str = "painkiller-agent:latest",
        client: Optional[Any] = None,
        plugin_dir: str = "/opt/superpowers",
        model: Optional[str] = None,
        network: Optional[str] = None,
    ):
        self.image_name = image_name
        self.plugin_dir = plugin_dir
        self.model = model or os.environ.get("PAINKILLER_AGENT_MODEL") or None
        # O contêiner do agente é criado como IRMÃO pelo socket do host, então
        # não entra na rede do compose por conta própria. Sem isto ele não
        # resolve o nome do proxy tradutor. Vazio = rede padrão (bridge).
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
        timeout_seconds: int = 86400,
        resume: bool = False,
        claude_session_id: Optional[str] = None,
    ) -> str:
        env_vars = {k: os.environ[k] for k in FORWARDED_ENV if k in os.environ}
        env_vars.update(env or {})
        self._require_credentials(env_vars)

        # Pasta para persistir configurações e memória do Claude Code
        claude_home = os.path.join(repo_path, ".painkiller", "claude_home")
        os.makedirs(claude_home, exist_ok=True)

        # A fila é criada no lado da API, pelo caminho local; o contêiner a
        # enxerga através do bind mount, que o daemon resolve por outro caminho.
        stdin_path = os.path.join(repo_path, ".painkiller", "agent-stdin.jsonl")
        os.makedirs(os.path.dirname(stdin_path), exist_ok=True)
        if not resume or not os.path.exists(stdin_path):
            with open(stdin_path, "w", encoding="utf-8"):
                pass
        self._stdin_files[session_id] = stdin_path

        agent_args = [
            "--print",
            "--verbose",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            # Emite os pedaços conforme o modelo produz, para o analista ver o
            # texto nascendo em vez de encarar um cronômetro por minutos.
            "--include-partial-messages",
            "--plugin-dir", self.plugin_dir,
            "--permission-mode", "bypassPermissions",
            "--add-dir", "/workspace",
        ]
        if self.model:
            agent_args.extend(["--model", self.model])

        if resume:
            if claude_session_id:
                agent_args.extend(["--resume", claude_session_id])
            else:
                agent_args.append("--continue")
        elif claude_session_id:
            agent_args.extend(["--session-id", claude_session_id])

        command = [
            "painkiller", "agent-run",
            "--stdin-file", "/workspace/" + STDIN_RELATIVE,
            "--idle-timeout", str(timeout_seconds),
            "--", *agent_args,
        ]

        container_name = f"pk-analysis-{session_id}-{uuid.uuid4().hex[:6]}"
        loop = asyncio.get_running_loop()
        volumes = {
            daemon_path(repo_path): {"bind": "/workspace", "mode": "rw"},
            daemon_path(claude_home): {"bind": "/home/node/.claude", "mode": "rw"},
        }
        container = await loop.run_in_executor(
            None,
            lambda: self.client.containers.run(
                self.image_name,
                command=command,
                name=container_name,
                volumes=volumes,
                environment=env_vars,
                working_dir="/workspace",
                network=self.network,
                # Permite que ANTHROPIC_BASE_URL aponte para um proxy publicado
                # numa porta do host quando o agente não está na rede do compose.
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
    def _require_credentials(env_vars: dict[str, str]) -> None:
        """Fail early and in pt-BR rather than letting the container die silently."""
        has_key = any(env_vars.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))
        has_cloud = any(env_vars.get(k) for k in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"))
        if has_key or has_cloud:
            return
        raise RuntimeError(
            "ANTHROPIC_API_KEY não está definida. A análise inicial roda o Claude Code, que fala a "
            "Messages API da Anthropic (/v1/messages) — a NVIDIA_API_KEY sozinha não serve, porque o "
            "NVIDIA Build só expõe o protocolo OpenAI. Escolha um destes e reinicie o servidor: "
            "(a) ANTHROPIC_API_KEY da Anthropic; (b) suba o proxy tradutor (serviço llm-proxy do "
            "docker-compose, ver docker/litellm-proxy.yaml) e aponte ANTHROPIC_BASE_URL para ele; "
            "(c) um NIM auto-hospedado, que já serve /v1/messages nativamente."
        )

    async def send(self, session_id: str, text: str) -> None:
        await self._append(session_id, {"type": "user", "message": {"role": "user", "content": text}})

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
        if not container:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._stop_sync, container)

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
    """Map one stream-json line from Claude Code onto a domain event."""
    if not line:
        return None
    try:
        data = json.loads(line)
    except ValueError:
        # Ruído de stderr (avisos do node, progresso de instalação) não é fatal.
        return AgentEvent(type=AgentEventType.ERROR, text=line, raw={"line": line})

    kind = data.get("type")
    if kind == "stream_event":
        return _from_stream_event(data)
    if kind == "assistant":
        return _from_assistant(data)
    if kind == "user":
        return _from_tool_result(data)
    if kind == "result":
        return AgentEvent(type=AgentEventType.RESULT, text=data.get("result") or "", raw=data)
    if kind == "system":
        return AgentEvent(type=AgentEventType.SYSTEM, text=data.get("subtype", ""), raw=data)
    return None


def _from_stream_event(data: dict) -> Optional[AgentEvent]:
    """Map an incremental chunk. Everything but visible text is ignored here.

    The canonical `assistant` message still arrives once the block closes, so a
    dropped delta costs nothing — the UI replaces the buffer with that text.
    """
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
    # signature_delta e input_json_delta não têm nada legível para mostrar.
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
