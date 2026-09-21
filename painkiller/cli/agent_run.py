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
import subprocess
import sys
import time
import click

#: Escrito pela API quando o analista encerra a conversa; fecha o stdin do
#: agente para que ele finalize o turno atual e saia com codigo proprio.
EOF_SENTINEL = "__painkiller_eof__"

POLL_INTERVAL_SECONDS = 0.2


@click.command(context_settings={"ignore_unknown_options": True})
@click.option("--stdin-file", required=True, help="JSONL file polled for agent input.")
@click.option("--agent-bin", default="agy", show_default=True, help="Executable to run as the agent.")
@click.option("--idle-timeout", default=3600, type=int, help="Seconds without agent exit before giving up.")
@click.argument("agent_args", nargs=-1, type=click.UNPROCESSED)
def agent_run(stdin_file: str, agent_bin: str, idle_timeout: int, agent_args: tuple):
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
        stdout=None,
        stderr=None,
        text=True,
        bufsize=1,
    )

    offset = 0
    pending = ""
    stdin_closed = False
    deadline = time.monotonic() + idle_timeout if idle_timeout > 0 else 0

    try:
        while True:
            code = proc.poll()
            if code is not None:
                return sys.exit(code)

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


def _is_eof(line: str) -> bool:
    try:
        return json.loads(line).get("type") == EOF_SENTINEL
    except (ValueError, AttributeError):
        return False
