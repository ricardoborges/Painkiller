"""Bridge a file-backed message queue into an interactive agent's stdin.

This runs *inside* the worker container. The API cannot reliably hold a
bidirectional `docker attach` socket open across platforms (npipe on Windows,
multiplexed frame headers when there is no TTY), so instead it appends JSONL
messages to a file on the bind-mounted workspace. This command tails that file
and feeds each new line to the agent's stdin, while the agent's stdout is
inherited straight through to the container logs.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
from typing import Optional

import click

#: Escrito pela API quando o analista encerra a conversa; fecha o stdin do
#: agente para que ele finalize o turno atual e saia com codigo proprio.
EOF_SENTINEL = "__painkiller_eof__"

POLL_INTERVAL_SECONDS = 0.2


@click.command(context_settings={"ignore_unknown_options": True})
@click.option("--stdin-file", required=True, help="JSONL file polled for agent input.")
@click.option("--agent-bin", default="agy", show_default=True, help="Executable to run as the agent.")
@click.option("--idle-timeout", default=3600, type=int, help="Seconds without agent exit before giving up.")
@click.option("--stdin-offset", default=0, type=int, help="Byte offset in --stdin-file where unanswered input starts.")
@click.option(
    "--fail-on-error-result",
    is_flag=True,
    help="Stop with exit 1 when the agent emits a stream-json `result` with is_error.",
)
@click.option(
    "--agent-log",
    default=None,
    help="JSON log the agent writes; auth/billing errors found there end the run (implies stdout relay).",
)
@click.argument("agent_args", nargs=-1, type=click.UNPROCESSED)
def agent_run(
    stdin_file: str,
    agent_bin: str,
    idle_timeout: int,
    stdin_offset: int,
    fail_on_error_result: bool,
    agent_log: Optional[str],
    agent_args: tuple,
):
    """Run the agent, forwarding lines appended to --stdin-file into its stdin."""
    os.makedirs(os.path.dirname(stdin_file) or ".", exist_ok=True)
    if not os.path.exists(stdin_file):
        with open(stdin_file, "w", encoding="utf-8"):
            pass

    # Assegura que o plugin superpowers esteja populado mesmo se ~/.gemini for montado limpo do host
    gemini_plugin_dir = os.path.expanduser("~/.gemini/config/plugins/superpowers")
    if os.path.exists("/opt/superpowers") and not os.path.exists(gemini_plugin_dir):
        try:
            import shutil
            os.makedirs(os.path.dirname(gemini_plugin_dir), exist_ok=True)
            shutil.copytree("/opt/superpowers", gemini_plugin_dir, dirs_exist_ok=True)
        except Exception:
            pass

    # Assegura que o Antigravity CLI use autenticação direta via GEMINI_API_KEY
    gemini_settings_file = os.path.expanduser("~/.gemini/antigravity-cli/settings.json")
    try:
        os.makedirs(os.path.dirname(gemini_settings_file), exist_ok=True)
        settings_data = {}
        if os.path.exists(gemini_settings_file):
            try:
                with open(gemini_settings_file, "r", encoding="utf-8") as f:
                    settings_data = json.load(f)
            except Exception:
                settings_data = {}
        if settings_data.get("modelProvider") != "gemini":
            settings_data["modelProvider"] = "gemini"
            with open(gemini_settings_file, "w", encoding="utf-8") as f:
                json.dump(settings_data, f, indent=2)
    except Exception:
        pass

    proc = subprocess.Popen(
        [agent_bin, *agent_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE if fail_on_error_result else None,
        stderr=None,
        text=True,
        bufsize=1,
    )

    # O maki relata chave recusada ou falta de saldo num `result` com is_error
    # e segue vivo esperando o próximo turno; aqui isso encerra o contêiner,
    # como a falha de qualquer outro harness.
    failed = threading.Event()
    relay = None
    if fail_on_error_result:
        relay = threading.Thread(target=_relay_stdout, args=(proc.stdout, failed), daemon=True)
        relay.start()
    if agent_log:
        # No modo SDK o maki não emite `result` quando a chave é recusada: fica
        # "esperando reautenticação" e só registra isso no próprio log.
        threading.Thread(target=_watch_agent_log, args=(agent_log, failed), daemon=True).start()

    # Retomando, o que está antes do offset já foi respondido pelo contêiner
    # anterior; reenviar repetiria a conversa inteira ao agente.
    offset = stdin_offset
    pending = ""
    stdin_closed = False
    deadline = time.monotonic() + idle_timeout if idle_timeout > 0 else 0

    try:
        while True:
            if failed.is_set():
                proc.kill()
                proc.wait()
                return sys.exit(1)

            code = proc.poll()
            if code is not None:
                # O `result` costuma ser a última linha: ela precisa chegar ao log.
                if relay is not None:
                    relay.join(timeout=5)
                return sys.exit(1 if failed.is_set() else code)

            if idle_timeout > 0 and time.monotonic() > deadline:
                proc.kill()
                return sys.exit(124)

            if not stdin_closed:
                try:
                    size = os.path.getsize(stdin_file)
                except OSError:
                    size = offset

                if size > offset:
                    if idle_timeout > 0:
                        deadline = time.monotonic() + idle_timeout
                    with open(stdin_file, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(offset)
                        chunk = f.read()
                        offset = f.tell()
                    pending += chunk

                    # Só linhas completas são repassadas: um append parcial do
                    # host não pode virar JSON truncado no stdin do agente.
                    while "\n" in pending:
                        line, pending = pending.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        if _is_eof(line):
                            proc.stdin.close()
                            stdin_closed = True
                            break
                        proc.stdin.write(line + "\n")
                        proc.stdin.flush()

            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        proc.kill()
        return sys.exit(130)


_stdout_lock = threading.Lock()

#: Erros de API que não se resolvem sozinhos: chave recusada, sem saldo, proibido.
_FATAL_API_ERROR = re.compile(r"API error \((401|402|403)\)|auth error|insufficient balance", re.IGNORECASE)


def _relay_stdout(stream, failed: threading.Event) -> None:
    """Pass the agent's stdout through, flagging a stream-json error result."""
    for line in stream:
        with _stdout_lock:
            sys.stdout.write(line)
            sys.stdout.flush()
        if _is_error_result(line):
            failed.set()


def _watch_agent_log(path: str, failed: threading.Event) -> None:
    """Tail the agent's JSON log and turn a fatal API error into an error `result`."""
    # Só o que for escrito depois de subirmos interessa; um log que ainda não
    # existe é lido desde o começo, quando aparecer.
    try:
        offset = os.path.getsize(path)
    except OSError:
        offset = 0
    while not failed.is_set():
        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
        if size is not None:
            if size < offset:
                offset = 0  # rotacionado
            elif size > offset:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(offset)
                    chunk = f.read()
                    offset = f.tell()
                for line in chunk.splitlines():
                    detail = _fatal_log_error(line)
                    if detail:
                        with _stdout_lock:
                            print(json.dumps({"type": "result", "subtype": "error", "is_error": True, "result": detail}), flush=True)
                        failed.set()
                        return
        time.sleep(POLL_INTERVAL_SECONDS)


def _fatal_log_error(line: str) -> Optional[str]:
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if not isinstance(entry, dict) or entry.get("level") not in ("WARN", "ERROR"):
        return None
    fields = entry.get("fields") or {}
    text = f"{fields.get('message', '')} {fields.get('error', '')}".strip()
    return text if _FATAL_API_ERROR.search(text) else None


def _is_error_result(line: str) -> bool:
    try:
        data = json.loads(line)
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("type") == "result" and bool(data.get("is_error"))


def _extract_prompt(line: str) -> str:
    try:
        data = json.loads(line)
        if isinstance(data, dict):
            msg = data.get("message")
            if isinstance(msg, dict) and "content" in msg:
                return str(msg["content"])
            for key in ("prompt", "content", "text"):
                if key in data:
                    return str(data[key])
    except Exception:
        pass
    return line


def _is_eof(line: str) -> bool:
    try:
        return json.loads(line).get("type") == EOF_SENTINEL
    except (ValueError, AttributeError):
        return False
