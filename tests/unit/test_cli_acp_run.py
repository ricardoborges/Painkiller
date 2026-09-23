"""Unit tests for `painkiller acp-run`, the DeepSeek Harness (ACP) bridge.

A fake ACP server stands in for `dsh --profile acp`: what matters is that the
bridge speaks the protocol and re-emits the agent's activity in the same
stream-json envelope `agy` produces, so the rest of Painkiller cannot tell the
harnesses apart.
"""

import json
import sys
import textwrap

import pytest
from click.testing import CliRunner

from painkiller.adapters.sandbox.docker_agent_session import parse_agent_line
from painkiller.cli import acp_run as bridge
from painkiller.core.domain.models import AgentEventType
from painkiller.core.usage import parse_task_usage

FAKE_SERVER = textwrap.dedent(
    r'''
    import json, os, sys
    sys.stdin.reconfigure(encoding="utf-8"); sys.stdout.reconfigure(encoding="utf-8")
    mode = os.environ.get("FAKE_ACP_MODE", "ok")
    home = os.environ["DSH_HOME"]
    turns = {}

    def send(msg):
        sys.stdout.write(json.dumps(msg) + "\n"); sys.stdout.flush()

    def update(sid, upd):
        send({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": sid, "update": upd}})

    seq = [0]

    def write_usage(sid):
        # O log da sessão do dsh: cada mensagem do modelo traz sua contagem.
        d = os.path.join(home, "sessions", "--w--", sid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "session.v3.jsonl"), "a") as f:
            for event in (
                {"type": "assistant/message", "data": {
                    "message": {"source": {"model": "deepseek-v4-flash"}},
                    "usage": {"inputTokens": 100, "outputTokens": 10, "cacheReadTokens": 1000}}},
                {"type": "turn/end", "data": {"reason": {"kind": "completed"}}},
            ):
                seq[0] += 1
                event["seq"] = seq[0]
                f.write(json.dumps(event) + "\n")

    config = [{"id": "model", "currentValue": "[\"deepseek-official\",\"deepseek-v4-flash\"]",
               "options": [{"group": "g", "options": [
                   {"value": "[\"deepseek-official\",\"deepseek-v4-flash\"]", "name": "DeepSeek-V4-Flash"},
                   {"value": "[\"deepseek-official\",\"deepseek-v4-pro\"]", "name": "DeepSeek-V4-Pro"}]}]}]

    for line in sys.stdin:
        msg = json.loads(line)
        if "method" not in msg:
            with open(os.path.join(home, "replies.jsonl"), "a") as f:
                f.write(json.dumps(msg) + "\n")
            continue
        m, p, i = msg["method"], msg.get("params") or {}, msg.get("id")
        with open(os.path.join(home, "calls.jsonl"), "a") as f:
            f.write(json.dumps(msg) + "\n")
        if m == "initialize":
            send({"jsonrpc": "2.0", "id": i, "result": {"protocolVersion": 1}})
        elif m == "session/new":
            send({"jsonrpc": "2.0", "id": i, "result": {"sessionId": "sess-1", "configOptions": config}})
        elif m == "session/resume":
            if p["sessionId"] == "sess-1":
                send({"jsonrpc": "2.0", "id": i, "result": {"configOptions": config}})
            else:
                send({"jsonrpc": "2.0", "id": i, "error": {"code": -32002, "message": "not found"}})
        elif m == "session/set_config_option":
            config[0]["currentValue"] = p["value"]
            send({"jsonrpc": "2.0", "id": i, "result": {"configOptions": config}})
        elif m == "session/prompt":
            sid = p["sessionId"]
            if mode == "quota":
                send({"jsonrpc": "2.0", "id": i, "error": {"code": -32603, "message": "Insufficient Balance"}})
                continue
            turns[sid] = turns.get(sid, 0) + 1
            text = p["prompt"][0]["text"]
            update(sid, {"sessionUpdate": "agent_thought_chunk", "messageId": "m1", "content": {"type": "text", "text": "pensando"}})
            update(sid, {"sessionUpdate": "agent_message_chunk", "messageId": "m1", "content": {"type": "text", "text": "Vou olhar."}})
            send({"jsonrpc": "2.0", "id": 999, "method": "session/request_permission", "params": {
                "sessionId": sid, "options": [
                    {"optionId": "no", "kind": "reject_once"}, {"optionId": "yes", "kind": "allow_once"}]}})
            update(sid, {"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "bash", "status": "in_progress", "rawInput": {"command": "ls"}})
            update(sid, {"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed"})
            update(sid, {"sessionUpdate": "agent_message_chunk", "messageId": "m2", "content": {"type": "text", "text": "Eco: " + text}})
            write_usage(sid)
            send({"jsonrpc": "2.0", "id": i, "result": {"stopReason": "end_turn"}})
        elif m == "session/close":
            send({"jsonrpc": "2.0", "id": i, "result": {}})
    '''
)


@pytest.fixture
def fake_dsh(tmp_path, monkeypatch):
    server = tmp_path / "fake_acp.py"
    server.write_text(FAKE_SERVER, encoding="utf-8")
    home = tmp_path / "dsh_home"
    home.mkdir()
    monkeypatch.setenv("DSH_HOME", str(home))
    monkeypatch.delenv("PAINKILLER_DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("PAINKILLER_DEEPSEEK_EFFORT", raising=False)
    monkeypatch.setattr(bridge, "DSH_ARGV", [sys.executable, str(server)])
    monkeypatch.setattr(bridge, "USAGE_SETTLE_SECONDS", 0.5)

    def read(name="calls.jsonl"):
        path = home / name
        if not path.exists():
            return []
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]

    return read


def _invoke(args):
    result = CliRunner().invoke(bridge.acp_run, args, catch_exceptions=False)
    lines = [l for l in result.output.splitlines() if l.strip()]
    return result.exit_code, lines


def _events(lines):
    return [e for e in (parse_agent_line(l) for l in lines) if e is not None]


def test_one_shot_emits_agy_envelope(tmp_path, fake_dsh):
    code, lines = _invoke(["--prompt", "faça X", "--cwd", str(tmp_path)])

    assert code == 0
    events = _events(lines)
    types = [e.type for e in events]
    assert types == [
        AgentEventType.SYSTEM,  # init
        AgentEventType.THINKING_DELTA,
        AgentEventType.ASSISTANT_DELTA,
        AgentEventType.TOOL_USE,
        AgentEventType.TOOL_RESULT,
        AgentEventType.ASSISTANT_DELTA,
        AgentEventType.RESULT,
    ]
    init = json.loads(lines[0])
    assert init["init"] == {"conversation_id": "sess-1", "model": "deepseek-v4-flash"}
    assert events[3].text == "bash"
    assert events[3].raw["step_update"]["tool_input"] == {"command": "ls"}
    # A fala anterior à ferramenta já foi fechada pelo TOOL_USE.
    assert events[-1].text == "Eco: faça X"


def test_permission_request_is_granted(tmp_path, fake_dsh):
    _invoke(["--prompt", "x", "--cwd", str(tmp_path)])
    # A opção de permitir, não a primeira da lista: o equivalente ao
    # --dangerously-skip-permissions do agy.
    assert fake_dsh("replies.jsonl") == [
        {"jsonrpc": "2.0", "id": 999, "result": {"outcome": {"outcome": "selected", "optionId": "yes"}}}
    ]


def test_turn_usage_is_reported_for_accounting(tmp_path, fake_dsh):
    _, lines = _invoke(["--prompt", "x", "--cwd", str(tmp_path)])

    result = json.loads(lines[-1])
    assert result["model"] == "deepseek-v4-flash"
    assert result["result"]["usage"] == {
        "input_tokens": 100,
        "cache_read_input_tokens": 1000,
        "output_tokens": 10,
    }
    assert parse_task_usage("\n".join(lines)) == (1100, 10, None, "deepseek-v4-flash")


def test_model_env_selects_advertised_option(tmp_path, fake_dsh, monkeypatch):
    monkeypatch.setenv("PAINKILLER_DEEPSEEK_MODEL", "deepseek-v4-pro")
    _, lines = _invoke(["--prompt", "x", "--cwd", str(tmp_path)])

    assert json.loads(lines[0])["init"]["model"] == "deepseek-v4-pro"
    set_calls = [c for c in fake_dsh() if c["method"] == "session/set_config_option"]
    assert set_calls[0]["params"]["value"] == '["deepseek-official","deepseek-v4-pro"]'


def test_prompt_failure_becomes_harness_error(tmp_path, fake_dsh, monkeypatch):
    monkeypatch.setenv("FAKE_ACP_MODE", "quota")
    code, lines = _invoke(["--prompt", "x", "--cwd", str(tmp_path)])

    assert code == 1
    errors = [e for e in _events(lines) if e.type == AgentEventType.ERROR]
    assert errors and errors[-1].raw["harness_error"] == "QUOTA"
    assert "sem saldo" in errors[-1].text


def test_interactive_session_keeps_one_acp_session_and_resumes(tmp_path, fake_dsh):
    stdin = tmp_path / ".painkiller" / "agent-stdin.jsonl"
    stdin.parent.mkdir(parents=True)
    stdin.write_text(
        json.dumps({"type": "user", "message": {"content": "primeira"}}) + "\n"
        + json.dumps({"type": "user", "message": {"content": "segunda"}}) + "\n"
        + json.dumps({"type": "__painkiller_eof__"}) + "\n",
        encoding="utf-8",
    )
    code, lines = _invoke(["--stdin-file", str(stdin), "--cwd", str(tmp_path), "--session-key", "pk-1"])

    assert code == 0
    results = [e for e in _events(lines) if e.type == AgentEventType.RESULT]
    assert [r.text for r in results] == ["Eco: primeira", "Eco: segunda"]
    methods = [c["method"] for c in fake_dsh()]
    assert methods.count("session/new") == 1
    assert methods.count("session/prompt") == 2
    stored = json.loads((tmp_path / ".painkiller" / "dsh-sessions.json").read_text(encoding="utf-8"))
    assert stored == {"pk-1": "sess-1"}

    # O contêiner religado retoma a mesma sessão ACP e só responde o que veio
    # depois do offset que a API mediu — o EOF antigo não o derruba.
    answered = stdin.stat().st_size
    with open(stdin, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "message": {"content": "terceira"}}) + "\n")
        f.write(json.dumps({"type": "__painkiller_eof__"}) + "\n")
    code, lines = _invoke(
        ["--stdin-file", str(stdin), "--cwd", str(tmp_path), "--session-key", "pk-1",
         "--resume", "--stdin-offset", str(answered)]
    )
    assert code == 0
    results = [e for e in _events(lines) if e.type == AgentEventType.RESULT]
    assert [r.text for r in results] == ["Eco: terceira"]
    resumes = [c for c in fake_dsh() if c["method"] == "session/resume"]
    assert resumes[-1]["params"]["sessionId"] == "sess-1"
    assert json.loads(lines[0])["init"]["conversation_id"] == "sess-1"
