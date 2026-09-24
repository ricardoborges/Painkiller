"""Drive Unreal Agent (`unreal-agent-runner`) as a Painkiller agent.

This runs inside the Unreal Agent containers and plays the role `painkiller
acp-run` plays for `dsh`. The runner executes one JSON request per process and
writes every persisted session item (`Kind`/`Data`) to stdout; a `session_id`
makes the next process resume the same history, so one process per analyst
message still gives the interview its memory.

Everything is re-emitted in the Antigravity stream-json envelope (`init`,
`step_update`, `result`), so `parse_agent_line`, the analysis pump, the task
hub and usage accounting need nothing Unreal-specific. The `result` closing a
turn is emitted when the runner exits — only then is the turn really over; a
message item can be followed by more tool calls.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Optional

import click

from painkiller.cli.agent_run import POLL_INTERVAL_SECONDS, _extract_prompt, _is_eof

#: Onde as imagens instalam as skills do superpowers.
SKILLS_SOURCE = "/opt/superpowers/skills"

#: O runner só descobre skills em `<workspace>/.harness/skills`.
SKILLS_RELATIVE = os.path.join(".harness", "skills")

_emit_lock = threading.Lock()


def _emit(event: dict) -> None:
    line = json.dumps(event, ensure_ascii=False)
    with _emit_lock:
        print(line, flush=True)


def _emit_step(step: dict) -> None:
    _emit({"event": "step_update", "step_update": step})


def _emit_failure(detail: str) -> None:
    """Report a failed turn as a stream-json `result` with is_error.

    `parse_agent_line` já transforma esse formato num ERROR com
    `raw.harness_error` (chave recusada, sem saldo...), o mesmo caminho do maki.
    """
    _emit({"type": "result", "is_error": True, "result": detail})


class TurnTranslator:
    """Translate the runner's session items of one turn into Antigravity events."""

    def __init__(self) -> None:
        self.text = ""
        self.failure: Optional[str] = None
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self._tools: dict[str, str] = {}

    def feed(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            data = json.loads(line)
        except ValueError:
            _emit_system(line)
            return
        if not isinstance(data, dict):
            return
        if data.get("type") == "error":
            # O runner emite isto e sai com 1 quando a execução falha.
            self.failure = str(data.get("message") or "erro")
            return
        kind = data.get("Kind")
        payload = data.get("Data") if isinstance(data.get("Data"), dict) else {}
        if kind == "model_response":
            self._model_response(payload.get("Response") or {})
        elif kind == "tool_call_status":
            self._tool_status(payload)

    def _model_response(self, response: dict) -> None:
        usage = response.get("Usage") or {}
        # InputTokens já inclui os tokens de cache; OutputTokens, os de raciocínio.
        self.usage["input_tokens"] += int(usage.get("InputTokens") or 0)
        self.usage["output_tokens"] += int(usage.get("OutputTokens") or 0)
        failure = response.get("Failure")
        if isinstance(failure, dict) and (failure.get("Message") or failure.get("Code")):
            code = failure.get("Code") or ""
            message = failure.get("Message") or ""
            self.failure = f"{code}: {message}" if code and message else (message or code)
        for item in response.get("Output") or []:
            item_type = item.get("Type")
            item_data = item.get("Data") if isinstance(item.get("Data"), dict) else {}
            if item_type == "message":
                text = (item_data.get("Text") or "").strip()
                if text:
                    self.text = text
                    _emit_step({"step_type": "agent_response", "state": "DONE", "response": text})
            elif item_type == "tool_call":
                name = item_data.get("Name") or ""
                self._tools[item_data.get("CallID") or ""] = name
                _emit_step({"step_type": "tool", "state": "RUNNING", "tool_name": name})
            elif item_type == "reasoning":
                summary = item_data.get("Summary") or []
                text = "\n".join(summary) if isinstance(summary, list) else str(summary)
                if text.strip():
                    _emit_step({"step_type": "agent_response", "thinking_delta": text + "\n"})

    def _tool_status(self, payload: dict) -> None:
        status = payload.get("Status") if isinstance(payload.get("Status"), dict) else {}
        if status.get("WaitingFor"):
            # Ainda esperando operações: não terminou.
            return
        name = self._tools.get(payload.get("CallID") or "", "")
        state = "ERROR" if status.get("Error") else "DONE"
        _emit_step({"step_type": "tool", "state": state, "tool_name": name})


def _emit_system(line: str) -> None:
    """Runner diagnostics (stderr, stray lines): `parse_agent_line` shows them as SYSTEM."""
    with _emit_lock:
        print(f"unreal: {line}", flush=True)


def _setup_superpowers_skills(workspace: str) -> None:
    """Publish the superpowers skills where the runner looks, and keep them out of git.

    O workspace é o repositório do usuário: sem o exclude, o `git add -A` do
    `painkiller ask` e do orquestrador commitaria o link (ou a cópia).
    """
    target = os.path.join(workspace, SKILLS_RELATIVE)
    if os.path.isdir(SKILLS_SOURCE) and not os.path.lexists(target):
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.symlink(SKILLS_SOURCE, target)
        except OSError:
            # Bind mount do Windows pode recusar symlink: copia.
            try:
                shutil.copytree(SKILLS_SOURCE, target, dirs_exist_ok=True)
            except OSError as e:
                _emit_system(f"não foi possível publicar as skills: {e}")

    exclude = os.path.join(workspace, ".git", "info", "exclude")
    if not os.path.isdir(os.path.join(workspace, ".git")):
        return
    try:
        existing = ""
        if os.path.exists(exclude):
            with open(exclude, "r", encoding="utf-8") as f:
                existing = f.read()
        if "/.harness/" not in existing.splitlines():
            os.makedirs(os.path.dirname(exclude), exist_ok=True)
            with open(exclude, "a", encoding="utf-8") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write("/.harness/\n")
    except OSError as e:
        _emit_system(f"não foi possível atualizar .git/info/exclude: {e}")


def _run_turn(
    agent_bin: str,
    workspace: str,
    session_directory: str,
    session_id: Optional[str],
    model: str,
    text: str,
) -> bool:
    """Run one runner process for one user message; True when the turn succeeded."""
    request: dict = {"messages": [{"role": "user", "content": text}]}
    if session_id:
        request["session_id"] = session_id
    cmd = [agent_bin, "-workspace", workspace, "-session-directory", session_directory]

    translator = TurnTranslator()
    try:
        # A requisição vai pelo stdin: as instruções de uma tarefa podem passar
        # do limite de tamanho de um argumento.
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as e:
        _emit_failure(f"não foi possível iniciar {agent_bin}: {e}")
        return False

    def drain_stderr() -> None:
        assert proc.stderr is not None
        for err_line in proc.stderr:
            if err_line.strip():
                _emit_system(err_line.rstrip())

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()

    assert proc.stdin is not None and proc.stdout is not None
    try:
        proc.stdin.write(json.dumps(request, ensure_ascii=False))
        proc.stdin.close()
    except OSError:
        pass
    for out_line in proc.stdout:
        translator.feed(out_line)
    proc.wait()
    stderr_thread.join(timeout=5)

    if proc.returncode != 0 or translator.failure:
        _emit_failure(translator.failure or f"unreal-agent-runner saiu com código {proc.returncode}")
        return False

    payload: dict = {"response": translator.text}
    if any(translator.usage.values()):
        payload["usage"] = translator.usage
    _emit({"event": "result", "result": payload, "model": model})
    return True


@click.command()
@click.option("--stdin-file", default=None, help="JSONL file polled for analyst messages (interactive mode).")
@click.option("--prompt", default=None, help="Run a single turn with this text and exit (one-shot mode).")
@click.option("--session-id", default=None, help="Runner session id; the same id resumes the same history.")
@click.option("--workspace", default="/workspace", show_default=True, help="Workspace directory.")
@click.option(
    "--session-directory",
    default="/root/.local/state/unreal-agent/sessions",
    show_default=True,
    help="Directory where the runner persists sessions.",
)
@click.option("--agent-bin", default="unreal-agent-runner", show_default=True, help="Binary to run.")
@click.option("--stdin-offset", default=0, type=int, help="Byte offset in --stdin-file where unanswered input starts.")
@click.option("--idle-timeout", default=3600, type=int, help="Seconds without input before giving up.")
def unreal_run(
    stdin_file: Optional[str],
    prompt: Optional[str],
    session_id: Optional[str],
    workspace: str,
    session_directory: str,
    agent_bin: str,
    stdin_offset: int,
    idle_timeout: int,
):
    """Run Unreal Agent, emitting Antigravity-style stream-json."""
    if not stdin_file and prompt is None:
        raise click.UsageError("informe --stdin-file ou --prompt")

    _setup_superpowers_skills(workspace)
    os.makedirs(session_directory, exist_ok=True)
    model = os.environ.get("UNREAL_HARNESS_LLM_MODEL") or ""
    _emit({"event": "init", "init": {"conversation_id": session_id or "", "model": model}})

    if prompt is not None:
        ok = _run_turn(agent_bin, workspace, session_directory, session_id, model, prompt)
        return sys.exit(0 if ok else 1)

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
            if idle_timeout > 0 and time.monotonic() > deadline:
                return sys.exit(124)

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
                        return sys.exit(0)
                    text = _extract_prompt(line)
                    if not text:
                        continue
                    if not _run_turn(agent_bin, workspace, session_directory, session_id, model, text):
                        # Sem saldo, chave recusada...: a sessão continua gravada e
                        # pode ser retomada depois que o problema for resolvido.
                        return sys.exit(1)
                    if idle_timeout > 0:
                        deadline = time.monotonic() + idle_timeout

            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        return sys.exit(130)
