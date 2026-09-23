"""Docker adapter for interactive agent sessions (Antigravity CLI + Superpowers)."""

import asyncio
import json
import logging
import os
import re
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
    "PAINKILLER_DEEPSEEK_MODEL",
    "PAINKILLER_DEEPSEEK_EFFORT",
    "PAINKILLER_MAKI_MODEL",
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


#: Harnesses que autenticam com a chave DeepSeek (do projeto ou do .env).
DEEPSEEK_KEY_HARNESSES = frozenset({"deepseek_superpowers", "maki_superpowers"})


def maki_model() -> str:
    """Model spec (provider/model-id) for maki; DeepSeek, as its key is the one passed."""
    return os.environ.get("PAINKILLER_MAKI_MODEL") or "deepseek/deepseek-v4-pro"


#: Log JSON do maki; no modo SDK é o único lugar onde uma chave recusada aparece.
MAKI_LOG = "/root/.local/logs/maki/maki.log"

_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def maki_session_file(session_uuid: str) -> str:
    """File maki writes for `--session-id <uuid>`: the UUID's 128 bits in base58."""
    try:
        number = uuid.UUID(session_uuid).int
    except ValueError:
        return f"{session_uuid}.jsonl"
    digits = ""
    while number:
        number, rest = divmod(number, 58)
        digits = _BASE58[rest] + digits
    return f"{digits or _BASE58[0]}.jsonl"


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
        model: Optional[str] = None,
    ) -> str:
        harness_type = getattr(harness, "value", harness) or "agy_superpowers"
        env_vars = {k: os.environ[k] for k in FORWARDED_ENV if k in os.environ}
        env_vars.update(env or {})
        if api_key:
            if harness_type in DEEPSEEK_KEY_HARNESSES:
                env_vars["DEEPSEEK_API_KEY"] = api_key
            else:
                env_vars["GEMINI_API_KEY"] = api_key
        self._require_credentials(env_vars, harness=harness_type)

        # Pasta para persistir configurações e memória do Antigravity CLI
        gemini_home = os.path.join(repo_path, ".painkiller", "gemini_home")
        if harness_type not in DEEPSEEK_KEY_HARNESSES:
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
            if model:
                env_vars["PAINKILLER_DEEPSEEK_MODEL"] = model
            # `painkiller acp-run` mantém uma sessão ACP do dsh viva e emite o
            # mesmo stream-json do agy. A chave da sessão do Painkiller acha a
            # sessão ACP de novo quando o contêiner é religado.
            command = [
                "painkiller", "acp-run",
                "--stdin-file", "/workspace/" + STDIN_RELATIVE,
                "--idle-timeout", str(timeout_seconds),
            ]
            if claude_session_id:
                command.extend(["--session-key", claude_session_id])
            if resume:
                # O que já está na fila foi respondido pelo contêiner anterior.
                command.extend(["--resume", "--stdin-offset", str(os.path.getsize(stdin_path))])
            # Histórico e contagem de tokens do dsh sobrevivem ao contêiner.
            dsh_home = os.path.join(repo_path, ".painkiller", "dsh_home")
            volumes = {daemon_path(repo_path): {"bind": "/workspace", "mode": "rw"}}
            for sub in ("sessions", "storages"):
                os.makedirs(os.path.join(dsh_home, sub), exist_ok=True)
                volumes[daemon_path(os.path.join(dsh_home, sub))] = {
                    "bind": f"/root/.dsh/{sub}",
                    "mode": "rw",
                }
        elif harness_type == "maki_superpowers":
            image = os.environ.get("PAINKILLER_AGENT_MAKI_IMAGE") or "painkiller-agent-maki:latest"
            # O maki fala o stream-json do Claude Code nos dois sentidos, então
            # a mesma ponte de fila do agy serve. A sessão é gravada sob o id do
            # Painkiller e retomada por ele (`--session`).
            maki_state = os.path.join(repo_path, ".painkiller", "maki_home")
            # Sem `sessions/` o maki nem grava a sessão num diretório montado vazio.
            os.makedirs(os.path.join(maki_state, "sessions", "locks"), exist_ok=True)
            has_saved = bool(claude_session_id) and os.path.exists(
                os.path.join(maki_state, "sessions", maki_session_file(claude_session_id))
            )
            agent_args = [
                "--trust", "--yolo", "--print",
                "--input-format", "stream-json",
                "--output-format", "stream-json",
                "--include-partial-messages",
                "--model", model or maki_model(),
            ]
            if claude_session_id:
                # Retomar exige que a sessão exista; se o contêiner caiu antes
                # do primeiro turno, começa de novo sob o mesmo id.
                flag = "--session" if resume and has_saved else "--session-id"
                agent_args.extend([flag, claude_session_id])
            elif resume:
                agent_args.append("--continue")
            command = [
                "painkiller", "agent-run",
                "--agent-bin", "maki",
                "--stdin-file", "/workspace/" + STDIN_RELATIVE,
                "--idle-timeout", str(timeout_seconds),
                "--fail-on-error-result",
                "--agent-log", MAKI_LOG,
            ]
            if resume:
                # O que já está na fila foi respondido pelo contêiner anterior.
                command.extend(["--stdin-offset", str(os.path.getsize(stdin_path))])
            command.extend(["--", *agent_args])
            volumes = {
                daemon_path(repo_path): {"bind": "/workspace", "mode": "rw"},
                daemon_path(maki_state): {"bind": "/root/.local/state/maki", "mode": "rw"},
            }
        else:
            image = self.image_name
            agent_args = [
                "--model", model or self.model,
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
        try:
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
        except docker.errors.ImageNotFound as e:
            # A imagem não existe localmente e o docker-py tenta um pull do
            # Docker Hub, que falha com um 404 cru. Diz o que fazer.
            raise RuntimeError(
                f"A imagem do agente '{image}' não foi encontrada no Docker. "
                "Construa as imagens dos harnesses com: docker compose --profile build build"
            ) from e
        self._containers[session_id] = container

        # O prompt inicial entra pela mesma fila: só envia se for nova sessão
        if not resume and prompt:
            await self.send(session_id, prompt)
        return container_name

    @staticmethod
    def _require_credentials(env_vars: dict[str, str], harness: str = "agy_superpowers") -> None:
        """Fail early and in pt-BR rather than letting the container die silently."""
        if harness in DEEPSEEK_KEY_HARNESSES:
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
        if line.startswith("dsh: reasoning:"):
            text = line[len("dsh: reasoning:"):].strip()
            return AgentEvent(type=AgentEventType.THINKING_DELTA, text=(text + "\n") if text else "", raw={"line": line})
        dsh_error = _parse_dsh_error(line)
        if dsh_error is not None:
            return dsh_error
        if line.startswith("dsh:"):
            return AgentEvent(type=AgentEventType.SYSTEM, text=line, raw={"line": line})
        if line.startswith("maki: failed to save session"):
            # Num bind mount do Windows o maki não consegue gravar o
            # `cwd_latest.json` (só usado por --continue); a sessão em si é
            # gravada e retomada normalmente por `--session`.
            return AgentEvent(type=AgentEventType.SYSTEM, text=line, raw={"line": line})
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
        if data.get("is_error"):
            # O maki (formato Claude Code) relata chave recusada, falta de saldo
            # etc. num `result` com is_error — e sai com código 0.
            return _harness_error(str(text or data.get("subtype") or "erro"), raw=data)
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


#: Falhas que o `dsh` anuncia no stderr como `dsh: <CÓDIGO>: <detalhe>`.
_DSH_ERROR_RE = re.compile(r"^dsh:\s*(?:([A-Z][A-Z_]+):|(fatal)\b:?)\s*(.*)$")

#: Mensagens para o analista; o detalhe original vai junto em `raw`. Os dois
#: harnesses que as disparam (dsh e maki) usam a mesma chave DeepSeek.
_HARNESS_ERROR_MESSAGES = {
    "QUOTA": (
        "A conta DeepSeek está sem saldo. Recarregue os créditos em "
        "platform.deepseek.com ou troque a chave de API do projeto."
    ),
    "AUTH": (
        "A DeepSeek recusou a chave de API. Confira a chave do projeto "
        "ou DEEPSEEK_API_KEY no .env."
    ),
}


def classify_harness_error(message: str) -> str:
    """Best-effort error code for a free-text harness failure."""
    upper = message.upper()
    if "BALANCE" in upper or "QUOTA" in upper or "402" in upper:
        return "QUOTA"
    if "AUTH" in upper or "API KEY" in upper or "401" in upper:
        return "AUTH"
    return "ERROR"


def _harness_error(detail: str, code: Optional[str] = None, raw: Optional[dict] = None) -> AgentEvent:
    """An ERROR the analyst must see — not container noise (see `harness_error`)."""
    code = (code or classify_harness_error(detail)).upper()
    message = _HARNESS_ERROR_MESSAGES.get(code) or f"O agente falhou: {detail}"
    return AgentEvent(
        type=AgentEventType.ERROR,
        text=message,
        raw={**(raw or {}), "harness_error": code, "detail": detail},
    )


def _parse_dsh_error(line: str) -> Optional[AgentEvent]:
    """Recognize a fatal `dsh` stderr line and describe it in pt-BR."""
    match = _DSH_ERROR_RE.match(line)
    if not match:
        return None
    code = (match.group(1) or match.group(2) or "").upper()
    detail = match.group(3).strip()
    return _harness_error(detail or line, code=code, raw={"line": line})


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
