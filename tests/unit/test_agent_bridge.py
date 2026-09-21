"""Unit tests for the file-backed stdin bridge that feeds the containerized agent.

The bridge exists because a bidirectional `docker attach` socket is not portable
(npipe on Windows, multiplexed frames without a TTY), so the API instead appends
JSONL to a file on the bind mount and this process forwards it.
"""

import subprocess
import sys
import textwrap
import threading
import time

import pytest

from painkiller.adapters.sandbox.docker_agent_session import EOF_SENTINEL

FAKE_AGENT = textwrap.dedent(
    """
    import sys
    for line in sys.stdin:
        line = line.strip()
        if line:
            print("ECHO:" + line, flush=True)
    print("DONE", flush=True)
    sys.exit(7)
    """
)


@pytest.fixture
def agent_script(tmp_path):
    path = tmp_path / "fake_agent.py"
    path.write_text(FAKE_AGENT, encoding="utf-8")
    return path


def _run_bridge(queue_file, agent_script, lines, delay=0.4):
    """Start the bridge, append `lines` to the queue, return (stdout, exit code)."""

    def feed():
        for line in lines:
            time.sleep(delay)
            with open(queue_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "painkiller.cli.main", "agent-run",
            "--stdin-file", str(queue_file),
            "--agent-bin", sys.executable,
            "--idle-timeout", "30",
            "--", str(agent_script),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    out, _ = proc.communicate(timeout=60)
    writer.join(timeout=5)
    return out, proc.returncode


def test_forwards_queued_lines_and_propagates_exit_code(tmp_path, agent_script):
    queue_file = tmp_path / "agent-stdin.jsonl"
    queue_file.write_text("", encoding="utf-8")

    out, code = _run_bridge(
        queue_file,
        agent_script,
        ['{"type":"user","message":{"role":"user","content":"oi"}}',
         '{"type":"' + EOF_SENTINEL + '"}'],
    )

    assert '"content":"oi"' in out
    assert "DONE" in out
    # O código de saída do agente tem que atravessar a ponte intacto: é ele que
    # o orquestrador lê para decidir entre FINISHED e FAILED.
    assert code == 7


def test_eof_sentinel_is_not_forwarded_to_the_agent(tmp_path, agent_script):
    queue_file = tmp_path / "agent-stdin.jsonl"
    queue_file.write_text("", encoding="utf-8")

    out, _ = _run_bridge(queue_file, agent_script, ['{"type":"' + EOF_SENTINEL + '"}'])

    assert EOF_SENTINEL not in out


def test_creates_the_queue_file_when_missing(tmp_path, agent_script):
    queue_file = tmp_path / "nested" / "agent-stdin.jsonl"

    out, code = _run_bridge(queue_file, agent_script, ['{"type":"' + EOF_SENTINEL + '"}'])

    assert queue_file.exists()
    assert code == 7


def test_agent_run_default_bin_is_agy():
    from click.testing import CliRunner
    from painkiller.cli.agent_run import agent_run

    runner = CliRunner()
    result = runner.invoke(agent_run, ["--help"])
    assert result.exit_code == 0
    # Verifica que o help exibe default: agy
    assert "agy" in result.output
    # Verifica diretamente no parâmetro click
    agent_bin_param = next(p for p in agent_run.params if p.name == "agent_bin")
    assert agent_bin_param.default == "agy"

