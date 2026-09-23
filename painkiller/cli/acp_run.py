"""Drive DeepSeek Harness (`dsh --profile acp`) as a Painkiller agent.

This runs *inside* the DeepSeek containers and plays the same role that
`agy --output-format stream-json` plays for the Antigravity images: it keeps
one persistent agent session alive, feeds it the analyst's messages, and writes
the agent's activity to stdout as stream-json in the Antigravity envelope
(`init`, `step_update`, `result`). Everything downstream — `parse_agent_line`,
the analysis pump, the task activity hub and usage accounting — therefore
treats both harnesses the same way.

`dsh` speaks the Agent Client Protocol (JSON-RPC over stdio). Two modes:

* interactive (`--stdin-file`): polls the JSONL queue the API appends to, one
  `session/prompt` per user line, until the EOF sentinel arrives;
* one-shot (`--prompt`): a single turn, then exit — the task-dispatch path.
"""

import glob
import json
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Any, Optional

import click

from painkiller.cli.agent_run import POLL_INTERVAL_SECONDS, _extract_prompt, _is_eof

#: Associação chave-do-Painkiller → sessionId do ACP, para retomar a conversa
#: depois que o contêiner reinicia. Fica no workspace (ignorado pelo git).
SESSION_MAP_RELATIVE = ".painkiller/dsh-sessions.json"

#: Servidor ACP do DeepSeek Harness (substituível nos testes).
DSH_ARGV = ["dsh", "--profile", "acp"]

#: Tempo máximo esperando o dsh gravar no log da sessão o fim do turno.
USAGE_SETTLE_SECONDS = 5.0


class AcpError(Exception):
    """A JSON-RPC error answered by the ACP server."""

    def __init__(self, error: dict):
        self.error = error or {}
        super().__init__(self.error.get("message") or "erro ACP")


class AcpClient:
    """Minimal ACP v1 client over the stdio of a `dsh --profile acp` process."""

    def __init__(self, argv: list[str], on_update):
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._on_update = on_update
        self._next_id = 0
        self._pending: dict[int, "queue.Queue[dict]"] = {}
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _write(self, message: dict) -> None:
        with self._lock:
            self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()

    def _read(self) -> None:
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                # O stdout do ACP é só protocolo; qualquer outra coisa vira diagnóstico.
                print(line, flush=True)
                continue
            if "method" in message:
                if "id" in message:
                    self._answer_request(message)
                elif message["method"] == "session/update":
                    self._on_update((message.get("params") or {}).get("update") or {})
                continue
            waiter = self._pending.pop(message.get("id"), None)
            if waiter is not None:
                waiter.put(message)
        # O processo morreu: destrava quem ainda espera resposta.
        for waiter in list(self._pending.values()):
            waiter.put({"error": {"message": "o processo dsh encerrou"}})
        self._pending.clear()

    def _answer_request(self, message: dict) -> None:
        """Answer agent → client requests. Permissions are granted, like agy's skip flag."""
        if message["method"] == "session/request_permission":
            options = (message.get("params") or {}).get("options") or []
            chosen = next(
                (o for o in options if o.get("kind") == "allow_always"),
                next((o for o in options if str(o.get("kind", "")).startswith("allow")), None),
            )
            if chosen is None and options:
                chosen = options[0]
            outcome = (
                {"outcome": "selected", "optionId": chosen["optionId"]}
                if chosen
                else {"outcome": "cancelled"}
            )
            self._write({"jsonrpc": "2.0", "id": message["id"], "result": {"outcome": outcome}})
            return
        self._write({
            "jsonrpc": "2.0",
            "id": message["id"],
            "error": {"code": -32601, "message": f"método não suportado: {message['method']}"},
        })

    def call(self, method: str, params: dict) -> Any:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
        waiter: "queue.Queue[dict]" = queue.Queue(maxsize=1)
        self._pending[request_id] = waiter
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        response = waiter.get()
        if "error" in response:
            raise AcpError(response["error"])
        return response.get("result") or {}

    def close(self, timeout: float = 30) -> int:
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return self.proc.wait()


class TurnTranslator:
    """Turn ACP `session/update`s into Antigravity-style stream-json lines."""

    def __init__(self):
        self.text_parts: list[str] = []
        self._last_message_id: Optional[str] = None
        self._tools: dict[str, str] = {}

    def reset(self) -> None:
        self.text_parts = []
        self._last_message_id = None

    def __call__(self, update: dict) -> None:
        kind = update.get("sessionUpdate")
        content = update.get("content") if isinstance(update.get("content"), dict) else {}
        if kind == "agent_message_chunk":
            text = content.get("text") or ""
            if not text:
                return
            # Cada passo do agente é uma mensagem inteira; separa passos diferentes.
            message_id = update.get("messageId")
            if self.text_parts and message_id != self._last_message_id:
                text = "\n\n" + text
            self._last_message_id = message_id
            self.text_parts.append(text)
            _emit_step({"step_type": "agent_response", "text_delta": text})
        elif kind == "agent_thought_chunk":
            text = content.get("text") or ""
            if text:
                _emit_step({"step_type": "agent_response", "thinking_delta": text + "\n"})
        elif kind == "tool_call":
            # O TOOL_USE fecha a fala anterior (vira um ASSISTANT próprio na
            # análise); o `result` só leva o que vier depois da última ferramenta.
            self.reset()
            call_id = update.get("toolCallId") or ""
            name = update.get("title") or update.get("kind") or "tool"
            self._tools[call_id] = name
            _emit_step({
                "step_type": "tool",
                "tool_name": name,
                "state": "ACTIVE",
                "tool_input": update.get("rawInput") or {},
            })
        elif kind == "tool_call_update":
            status = update.get("status")
            if status in ("completed", "failed"):
                name = self._tools.pop(update.get("toolCallId") or "", None) or update.get("title") or "tool"
                _emit_step({
                    "step_type": "tool",
                    "tool_name": name,
                    "state": "DONE" if status == "completed" else "ERROR",
                })

    @property
    def text(self) -> str:
        return "".join(self.text_parts).strip()


def _emit(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def _emit_step(step: dict) -> None:
    _emit({"event": "step_update", "step_update": step})


def _emit_failure(exc: Exception) -> None:
    """Report an ACP failure in the `dsh: <CÓDIGO>: <mensagem>` shape the parser knows."""
    error = exc.error if isinstance(exc, AcpError) else {}
    data = error.get("data") if isinstance(error.get("data"), dict) else {}
    # Import tardio: o módulo puxa o docker-py, e todo comando `painkiller`
    # (inclusive o `ask` do agente) carregaria isso na partida.
    from painkiller.adapters.sandbox.docker_agent_session import classify_harness_error

    message = str(data.get("message") or error.get("message") or exc)
    code = str(data.get("code") or data.get("kind") or "").upper() or classify_harness_error(message)
    print(f"dsh: {code}: {message}", flush=True)


# ---- seleção de modelo ---------------------------------------------------


def _find_option_value(config_options: list, config_id: str, wanted: str) -> Optional[str]:
    """Match `wanted` against an advertised select option, by value or name."""
    wanted_norm = wanted.strip().lower()
    for option in config_options or []:
        if option.get("id") != config_id:
            continue
        stack = list(option.get("options") or [])
        while stack:
            item = stack.pop(0)
            if "options" in item:
                stack.extend(item.get("options") or [])
                continue
            value = str(item.get("value", ""))
            candidates = {value.lower(), str(item.get("name", "")).lower()}
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list) and parsed:
                    candidates.add(str(parsed[-1]).lower())
            except ValueError:
                pass
            if wanted_norm in candidates:
                return value
    return None


def _current_model(config_options: list) -> str:
    for option in config_options or []:
        if option.get("id") == "model":
            value = option.get("currentValue") or ""
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list) and parsed:
                    return str(parsed[-1])
            except ValueError:
                pass
            return str(value)
    return ""


def _apply_config(client: AcpClient, session_id: str, config_options: list) -> list:
    """Honor PAINKILLER_DEEPSEEK_MODEL / PAINKILLER_DEEPSEEK_EFFORT when set."""
    for config_id, env_name in (("model", "PAINKILLER_DEEPSEEK_MODEL"), ("reasoning_effort", "PAINKILLER_DEEPSEEK_EFFORT")):
        wanted = os.environ.get(env_name)
        if not wanted:
            continue
        value = _find_option_value(config_options, config_id, wanted)
        if value is None:
            print(f"dsh: aviso: {env_name}={wanted} não é uma opção oferecida; mantendo o padrão", flush=True)
            continue
        try:
            result = client.call(
                "session/set_config_option",
                {"sessionId": session_id, "configId": config_id, "value": value},
            )
            config_options = result.get("configOptions") or config_options
        except AcpError as e:
            print(f"dsh: aviso: não foi possível ajustar {config_id}: {e}", flush=True)
    return config_options


# ---- sessão persistida ---------------------------------------------------


def _load_session_map(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_session_map(path: str, key: str, session_id: str) -> None:
    data = _load_session_map(path)
    data[key] = session_id
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def _open_session(client: AcpClient, cwd: str, session_key: Optional[str], resume: bool) -> tuple[str, list]:
    map_path = os.path.join(cwd, SESSION_MAP_RELATIVE)
    if resume and session_key:
        previous = _load_session_map(map_path).get(session_key)
        if previous:
            try:
                result = client.call("session/resume", {"sessionId": previous, "cwd": cwd, "mcpServers": []})
                return previous, result.get("configOptions") or []
            except AcpError as e:
                print(f"dsh: aviso: não foi possível retomar a sessão {previous}: {e}", flush=True)
    result = client.call("session/new", {"cwd": cwd, "mcpServers": []})
    session_id = result["sessionId"]
    if session_key:
        _save_session_map(map_path, session_key, session_id)
    return session_id, result.get("configOptions") or []


# ---- tokens --------------------------------------------------------------

#: Decodifica o log da sessão do dsh: JSONL em vários frames zstd concatenados.
#: O Python da imagem (3.11) não tem zstd; o Node, que o dsh já exige, tem.
_ZSTD_JSONL_JS = r"""
const z = require("zlib"), fs = require("fs");
const b = fs.readFileSync(process.argv[1]);
const magic = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);
const at = [];
for (let i = b.indexOf(magic); i !== -1; i = b.indexOf(magic, i + 1)) at.push(i);
for (let k = 0; k < at.length; k++) {
  try { process.stdout.write(z.zstdDecompressSync(b.subarray(at[k], at[k + 1] ?? b.length))); }
  catch (e) { /* frame parcial no fim de um log ainda sendo gravado */ }
}
"""


def _dsh_home() -> str:
    return os.environ.get("DSH_HOME") or os.path.expanduser("~/.dsh")


def _read_session_log(session_id: str) -> list[dict]:
    """Every event persisted in the session's dsh log (plain or zstd JSONL)."""
    events: list[dict] = []
    for path in glob.glob(os.path.join(_dsh_home(), "sessions", "*", session_id, "session.v*.jsonl*")):
        try:
            if path.endswith(".zstd"):
                text = subprocess.run(
                    ["node", "-e", _ZSTD_JSONL_JS, path],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                ).stdout
            else:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
        except (OSError, subprocess.SubprocessError):
            continue
        for line in text.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


class UsageMeter:
    """Token usage per turn, read from the `assistant/message` events of the dsh log.

    O ACP não informa tokens; o log da sessão sim, em cada mensagem do modelo.
    Contamos por número de sequência, então uma mensagem que só chegue ao disco
    depois do fim do turno entra no turno seguinte em vez de se perder.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        # Numa retomada, o que já está no log foi contado pelo contêiner anterior.
        self.counted_seq = max((int(e.get("seq") or 0) for e in _read_session_log(session_id)), default=0)
        self.model: Optional[str] = None

    def turn_usage(self) -> Optional[dict]:
        deadline = time.monotonic() + USAGE_SETTLE_SECONDS
        while True:
            events = _read_session_log(self.session_id)
            fresh = [e for e in events if int(e.get("seq") or 0) > self.counted_seq]
            # O log é gravado ao fim do turno; espera o `turn/end` aparecer.
            if any(e.get("type") == "turn/end" for e in fresh) or time.monotonic() >= deadline:
                break
            time.sleep(0.2)
        usage = {"input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0}
        for event in fresh:
            self.counted_seq = max(self.counted_seq, int(event.get("seq") or 0))
            if event.get("type") != "assistant/message":
                continue
            data = event.get("data") or {}
            counts = data.get("usage") or {}
            usage["input_tokens"] += int(counts.get("inputTokens") or 0) + int(counts.get("cacheWriteTokens") or 0)
            usage["cache_read_input_tokens"] += int(counts.get("cacheReadTokens") or 0)
            usage["output_tokens"] += int(counts.get("outputTokens") or 0)
            source = (data.get("message") or {}).get("source") or {}
            if source.get("model"):
                self.model = str(source["model"])
        return usage if any(usage.values()) else None


# ---- turnos --------------------------------------------------------------


def _run_turn(client: AcpClient, translator: TurnTranslator, session_id: str, model: str, text: str, meter: "UsageMeter") -> None:
    translator.reset()
    result = client.call(
        "session/prompt",
        {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]},
    )
    payload: dict = {"response": translator.text, "stop_reason": result.get("stopReason")}
    usage = meter.turn_usage()
    if usage:
        payload["usage"] = usage
    _emit({"event": "result", "result": payload, "model": meter.model or model})


def _start(cwd: str, session_key: Optional[str], resume: bool, translator: TurnTranslator):
    client = AcpClient(list(DSH_ARGV), translator)
    client.call("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
    session_id, config_options = _open_session(client, cwd, session_key, resume)
    config_options = _apply_config(client, session_id, config_options)
    model = _current_model(config_options)
    _emit({"event": "init", "init": {"conversation_id": session_id, "model": model}})
    return client, session_id, model, UsageMeter(session_id)


@click.command(context_settings={"ignore_unknown_options": True})
@click.option("--stdin-file", default=None, help="JSONL file polled for analyst messages (interactive mode).")
@click.option("--prompt", default=None, help="Run a single turn with this text and exit (one-shot mode).")
@click.option("--cwd", default="/workspace", show_default=True, help="Absolute workspace root for the session.")
@click.option("--session-key", default=None, help="Painkiller id used to find the ACP session again on resume.")
@click.option("--resume", is_flag=True, help="Resume the ACP session stored under --session-key.")
@click.option("--stdin-offset", default=0, type=int, help="Byte offset in --stdin-file where unanswered input starts.")
@click.option("--idle-timeout", default=3600, type=int, help="Seconds without input before giving up.")
def acp_run(
    stdin_file: Optional[str],
    prompt: Optional[str],
    cwd: str,
    session_key: Optional[str],
    resume: bool,
    stdin_offset: int,
    idle_timeout: int,
):
    """Run DeepSeek Harness over ACP, emitting Antigravity-style stream-json."""
    if not stdin_file and prompt is None:
        raise click.UsageError("informe --stdin-file ou --prompt")

    translator = TurnTranslator()
    try:
        client, session_id, model, meter = _start(cwd, session_key, resume, translator)
    except (AcpError, OSError) as e:
        _emit_failure(e)
        return sys.exit(1)

    def finish(code: int):
        try:
            client.call("session/close", {"sessionId": session_id})
        except AcpError:
            pass
        client.close()
        return sys.exit(code)

    if prompt is not None:
        try:
            _run_turn(client, translator, session_id, model, prompt, meter)
        except AcpError as e:
            _emit_failure(e)
            return finish(1)
        return finish(0)

    os.makedirs(os.path.dirname(stdin_file) or ".", exist_ok=True)
    if not os.path.exists(stdin_file):
        with open(stdin_file, "w", encoding="utf-8"):
            pass

    # Retomando, o que está antes do offset já foi respondido pelo contêiner
    # anterior. Quem mede é a API, no momento da religada: medir aqui perderia
    # uma mensagem enviada enquanto o contêiner ainda subia.
    offset = stdin_offset
    pending = ""
    deadline = time.monotonic() + idle_timeout if idle_timeout > 0 else 0

    try:
        while True:
            if client.proc.poll() is not None:
                print(f"dsh: fatal: o processo dsh encerrou com código {client.proc.returncode}", flush=True)
                return sys.exit(client.proc.returncode or 1)
            if idle_timeout > 0 and time.monotonic() > deadline:
                return finish(124)

            try:
                size = os.path.getsize(stdin_file)
            except OSError:
                size = offset

            if size > offset:
                with open(stdin_file, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(offset)
                    chunk = f.read()
                    offset = f.tell()
                pending += chunk

                # Só linhas completas: um append parcial do host não vira JSON truncado.
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    if _is_eof(line):
                        return finish(0)
                    try:
                        _run_turn(client, translator, session_id, model, _extract_prompt(line), meter)
                    except AcpError as e:
                        # Sem saldo, chave recusada...: a sessão continua gravada e
                        # pode ser retomada depois que o problema for resolvido.
                        _emit_failure(e)
                        return finish(1)
                    if idle_timeout > 0:
                        deadline = time.monotonic() + idle_timeout

            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        client.proc.kill()
        return sys.exit(130)
