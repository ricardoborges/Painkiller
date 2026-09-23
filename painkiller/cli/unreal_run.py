"""Drive Unreal Agent (`unreal-agent-runner`) as a Painkiller agent.

This runs inside the Unreal Agent containers and plays the same role that
`agy --output-format stream-json` and `painkiller acp-run` play: it keeps
one persistent agent session alive across turns, feeds it the analyst's messages,
and translates the session events into Painkiller's domain event stream
(`init`, `assistant`, `tool_use`, `result`).
"""

import json
import os
import subprocess
import sys
import time
from typing import List, Optional

import click

from painkiller.cli.agent_run import EOF_SENTINEL, POLL_INTERVAL_SECONDS, _extract_prompt, _is_eof
from painkiller.core.domain.models import AgentEvent, AgentEventType


def parse_unreal_line(line: str) -> List[AgentEvent]:
    """Parse one JSON line emitted by unreal-agent-runner into AgentEvent domain objects."""
    line = line.strip()
    if not line:
        return []
    try:
        data = json.loads(line)
    except Exception:
        return []

    events: List[AgentEvent] = []

    # Erro de execução (ex: authentication failed, invalid flag)
    if data.get("type") == "error" or data.get("Type") == "error":
        msg = data.get("message") or data.get("Message") or "erro"
        events.append(AgentEvent(type=AgentEventType.ERROR, text=msg, raw=data))
        return events

    kind = data.get("Kind")
    if not kind:
        # Se for um evento já envelopado
        if "type" in data and data.get("type") in ("assistant", "result", "system"):
            events.append(AgentEvent(type=AgentEventType(data["type"].upper()), text=data.get("text", ""), raw=data))
        return events

    data_payload = data.get("Data") or {}

    if kind == "model_response":
        resp = data_payload.get("Response") or {}
        output_items = resp.get("Output") or []
        for item in output_items:
            itype = item.get("Type")
            item_data = item.get("Data") or {}
            if itype == "message":
                text = item_data.get("Text") or ""
                events.append(AgentEvent(type=AgentEventType.ASSISTANT, text=text, raw=data))
                # Todo turno finalizado com texto produz também o evento RESULT
                events.append(AgentEvent(type=AgentEventType.RESULT, text=text, raw=data))
            elif itype == "tool_call":
                name = item_data.get("Name") or ""
                events.append(AgentEvent(type=AgentEventType.TOOL_USE, text=name, raw=data))
            elif itype == "reasoning":
                summary = item_data.get("Summary") or []
                text = " ".join(summary) if isinstance(summary, list) else str(summary)
                events.append(AgentEvent(type=AgentEventType.THINKING_DELTA, text=text, raw=data))

    elif kind == "tool_call_status":
        call_id = data_payload.get("CallID") or ""
        events.append(AgentEvent(type=AgentEventType.TOOL_RESULT, text=call_id, raw=data))

    return events


def _setup_superpowers_skills(workspace: str) -> None:
    """Ensure .harness/skills in the workspace is populated with Superpowers skills."""
    opt_superpowers = "/opt/superpowers/skills"
    harness_skills = os.path.join(workspace, ".harness", "skills")
    if os.path.exists(opt_superpowers) and not os.path.exists(harness_skills):
        try:
            os.makedirs(os.path.dirname(harness_skills), exist_ok=True)
            os.symlink(opt_superpowers, harness_skills)
        except Exception:
            pass


@click.command(context_settings={"ignore_unknown_options": True})
@click.option("--stdin-file", default=None, help="JSONL file polled for agent input in interactive session.")
@click.option("--session-id", default=None, help="Unique session ID for conversation history.")
@click.option("--workspace", default="/workspace", show_default=True, help="Workspace directory.")
@click.option("--session-directory", default="/root/.local/state/unreal-agent/sessions", help="Directory where sessions are persisted.")
@click.option("--agent-bin", default="unreal-agent-runner", show_default=True, help="Binary to run.")
@click.option("--idle-timeout", default=3600, type=int, help="Seconds before idle timeout.")
@click.option("--prompt", default=None, help="Single-shot prompt to run (task execution mode).")
def unreal_run(
    stdin_file: Optional[str],
    session_id: Optional[str],
    workspace: str,
    session_directory: str,
    agent_bin: str,
    idle_timeout: int,
    prompt: Optional[str],
):
    """Run Unreal Agent, bridging stdin messages or one-shot prompt."""
    _setup_superpowers_skills(workspace)
    os.makedirs(session_directory, exist_ok=True)

    # 1. Modo One-Shot (execução direta de tarefa no worker)
    if prompt:
        cmd = [agent_bin, "-workspace", workspace, "-session-directory", session_directory, "-p", prompt]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
        proc.wait()
        sys.exit(proc.returncode)

    # 2. Modo Interativo (análise inicial com fila .painkiller/agent-stdin.jsonl)
    if not stdin_file:
        click.echo("Erro: forneça --stdin-file ou --prompt", err=True)
        sys.exit(1)

    os.makedirs(os.path.dirname(stdin_file) or ".", exist_ok=True)
    if not os.path.exists(stdin_file):
        with open(stdin_file, "w", encoding="utf-8"):
            pass

    offset = 0
    sid = session_id or "unreal-session"
    last_activity = time.time()

    # Informa início do agente
    model_name = os.environ.get("UNREAL_HARNESS_LLM_MODEL") or os.environ.get("PAINKILLER_MAKI_MODEL") or "deepseek/deepseek-v4-pro"
    init_event = {"event": "init", "init": {"model": model_name}}
    sys.stdout.write(json.dumps(init_event) + "\n")
    sys.stdout.flush()

    while True:
        if not os.path.exists(stdin_file):
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        with open(stdin_file, "r", encoding="utf-8") as f:
            f.seek(offset)
            lines = f.readlines()
            offset = f.tell()

        if not lines:
            if time.time() - last_activity > idle_timeout:
                break
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        last_activity = time.time()

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            if _is_eof(line_str):
                sys.exit(0)

            user_prompt = _extract_prompt(line_str)
            if not user_prompt:
                continue

            # Prepara requisição JSON para o unreal-agent-runner
            req = {
                "session_id": sid,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            req_json = json.dumps(req)

            cmd = [agent_bin, "-workspace", workspace, "-session-directory", session_directory, req_json]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            assert proc.stdout is not None
            for out_line in proc.stdout:
                # Transmite as linhas diretamente para que parse_agent_line processe
                sys.stdout.write(out_line)
                sys.stdout.flush()

            proc.wait()
