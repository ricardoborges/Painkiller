"""CLI command for asking clarification and triggering exit 42."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
import click


@click.command()
@click.argument("question")
@click.option("--context", default="", help="Context or location summary for the question.")
def ask(question: str, context: str):
    """Pause execution, record a clarification question, commit WIP, and exit with code 42."""
    workspace = os.environ.get("PAINKILLER_WORKSPACE", os.getcwd())
    pk_dir = os.path.join(workspace, ".painkiller")
    os.makedirs(pk_dir, exist_ok=True)

    payload = {
        "question": question,
        "context_summary": context,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    clar_file = os.path.join(pk_dir, "clarification.json")
    with open(clar_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    # Attempt git WIP commit if git repo exists
    try:
        exclude_file = os.path.join(workspace, ".git", "info", "exclude")
        if os.path.exists(exclude_file):
            try:
                with open(exclude_file, "r", encoding="utf-8") as ef:
                    if ".painkiller" not in ef.read():
                        with open(exclude_file, "a", encoding="utf-8") as aef:
                            aef.write("\n.painkiller/\n")
            except Exception:
                pass
        subprocess.run(["git", "add", "-A"], cwd=workspace, capture_output=True, check=False)
        subprocess.run(
            ["git", "commit", "-m", f"wip: paused for clarification ({question[:40]})"],
            cwd=workspace,
            capture_output=True,
            check=False,
        )
    except Exception:
        pass

    click.echo(f"🤖 Painkiller: Pausing execution for clarification: {question}")
    sys.exit(42)
