"""Unit tests for the in-container `painkiller ask` CLI interruption protocol."""

import json
import os
import tempfile
from click.testing import CliRunner
from painkiller.cli.main import cli


def test_painkiller_ask_creates_json_and_exits_42():
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        # Run inside tmpdir
        result = runner.invoke(
            cli,
            ["ask", "Qual algoritmo de hash usar?", "--context", "auth.py:20"],
            env={"PAINKILLER_WORKSPACE": tmpdir},
        )
        assert result.exit_code == 42

        # Check clarification.json
        clar_path = os.path.join(tmpdir, ".painkiller", "clarification.json")
        assert os.path.exists(clar_path)

        with open(clar_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["question"] == "Qual algoritmo de hash usar?"
        assert data["context_summary"] == "auth.py:20"
        assert "timestamp" in data
