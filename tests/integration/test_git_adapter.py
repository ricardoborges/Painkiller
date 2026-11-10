"""Integration tests for GitCliAdapter."""

import os
import subprocess
import tempfile
import pytest
from painkiller.adapters.git.git_adapter import GitCliAdapter


@pytest.fixture
def temp_git_repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Initialize git repo in tmpdir
        subprocess.run(["git", "init", "-b", "main"], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmpdir, check=True)

        readme_file = os.path.join(tmpdir, "README.md")
        with open(readme_file, "w", encoding="utf-8") as f:
            f.write("# Hello\n")

        subprocess.run(["git", "add", "README.md"], cwd=tmpdir, check=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=tmpdir, check=True)
        yield tmpdir


@pytest.mark.asyncio
async def test_git_adapter_branch_commit_and_diff(temp_git_repo: str):
    adapter = GitCliAdapter()

    # Create new feature branch
    await adapter.create_branch(temp_git_repo, "feature/test-1", base_branch="main")

    # Add a file
    new_file = os.path.join(temp_git_repo, "test.txt")
    with open(new_file, "w", encoding="utf-8") as f:
        f.write("Line 1\nLine 2\n")

    assert await adapter.has_changes(temp_git_repo) is True

    # Commit WIP
    commit_hash = await adapter.commit_wip(temp_git_repo, "wip: add test file")
    assert len(commit_hash) >= 7

    # Get diff
    diff = await adapter.get_diff(temp_git_repo, base_branch="main")
    assert "+Line 1" in diff
    assert "+Line 2" in diff


@pytest.mark.asyncio
async def test_commit_paths_commits_only_the_given_paths(temp_git_repo: str):
    adapter = GitCliAdapter()

    spec_dir = os.path.join(temp_git_repo, "docs", "superpowers", "specs")
    os.makedirs(spec_dir)
    with open(os.path.join(spec_dir, "spec.md"), "w", encoding="utf-8") as f:
        f.write("# Spec\n")
    # Fora de docs/: não pode entrar no commit.
    with open(os.path.join(temp_git_repo, "scratch.txt"), "w", encoding="utf-8") as f:
        f.write("rascunho\n")

    sha = await adapter.commit_paths(temp_git_repo, ["docs"], "docs: spec")
    assert sha

    committed = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=temp_git_repo, check=True, capture_output=True, text=True,
    ).stdout.split()
    assert committed == ["docs/superpowers/specs/spec.md"]
    assert await adapter.has_changes(temp_git_repo) is True  # scratch.txt continua pendente

    # Sem mudanças novas em docs/, nada a commitar.
    assert await adapter.commit_paths(temp_git_repo, ["docs"], "docs: spec") is None
    assert await adapter.current_branch(temp_git_repo) == "main"


@pytest.mark.asyncio
async def test_commit_paths_ignores_missing_paths(temp_git_repo: str):
    adapter = GitCliAdapter()
    assert await adapter.commit_paths(temp_git_repo, ["docs"], "docs: nada") is None


@pytest.mark.asyncio
async def test_switch_branch_returns_to_default(temp_git_repo: str):
    adapter = GitCliAdapter()
    await adapter.create_branch(temp_git_repo, "feature/t1", base_branch="main")
    # Não rastreado atravessa o checkout sem impedir a troca.
    os.makedirs(os.path.join(temp_git_repo, ".painkiller"))
    with open(os.path.join(temp_git_repo, ".painkiller", "agent-stdin.jsonl"), "w") as f:
        f.write("{}\n")

    code, _ = await adapter.switch_branch(temp_git_repo, "main")
    assert code == 0
    assert await adapter.current_branch(temp_git_repo) == "main"


@pytest.mark.asyncio
async def test_switch_branch_refuses_with_tracked_changes(temp_git_repo: str):
    adapter = GitCliAdapter()
    await adapter.create_branch(temp_git_repo, "feature/t1", base_branch="main")
    with open(os.path.join(temp_git_repo, "README.md"), "a", encoding="utf-8") as f:
        f.write("meio caminho\n")

    code, out = await adapter.switch_branch(temp_git_repo, "main")
    assert code != 0
    assert "README.md" in out
    assert await adapter.current_branch(temp_git_repo) == "feature/t1"


def _commit(repo: str, name: str, content: str, message: str) -> None:
    with open(os.path.join(repo, name), "w", encoding="utf-8") as f:
        f.write(content)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True)


def _conflicting_branches(repo: str) -> None:
    """feature/a and main both rewrite README.md; the repo ends on feature/a."""
    subprocess.run(["git", "checkout", "-b", "feature/a"], cwd=repo, check=True, capture_output=True)
    _commit(repo, "README.md", "# Da tarefa\n", "task")
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
    _commit(repo, "README.md", "# Da principal\n", "main")
    subprocess.run(["git", "checkout", "feature/a"], cwd=repo, check=True, capture_output=True)


@pytest.mark.asyncio
async def test_conflicting_merge_is_aborted_and_the_repo_stays_usable(temp_git_repo: str):
    adapter = GitCliAdapter()
    _conflicting_branches(temp_git_repo)

    code, out = await adapter.merge_branch(temp_git_repo, source_branch="feature/a", target_branch="main")

    assert code != 0 and "CONFLICT" in out
    assert not os.path.exists(os.path.join(temp_git_repo, ".git", "MERGE_HEAD"))
    assert await adapter.has_changes(temp_git_repo) is False
    # Antes, todo checkout seguinte falhava com "resolve your current index first".
    await adapter.create_branch(temp_git_repo, "feature/b", base_branch="main")
    assert await adapter.current_branch(temp_git_repo) == "feature/b"
    await adapter.create_branch(temp_git_repo, "feature/a", base_branch="main")
    assert await adapter.current_branch(temp_git_repo) == "feature/a"


@pytest.mark.asyncio
async def test_abort_merge_heals_a_repo_left_mid_merge(temp_git_repo: str):
    adapter = GitCliAdapter()
    _conflicting_branches(temp_git_repo)
    subprocess.run(["git", "checkout", "main"], cwd=temp_git_repo, check=True, capture_output=True)
    subprocess.run(["git", "merge", "feature/a"], cwd=temp_git_repo, capture_output=True)

    assert await adapter.abort_merge(temp_git_repo) is True
    assert await adapter.abort_merge(temp_git_repo) is False
    assert await adapter.has_changes(temp_git_repo) is False


@pytest.mark.asyncio
async def test_sync_branch_brings_the_default_branch_in(temp_git_repo: str):
    adapter = GitCliAdapter()
    await adapter.create_branch(temp_git_repo, "feature/a", base_branch="main")
    subprocess.run(["git", "checkout", "main"], cwd=temp_git_repo, check=True, capture_output=True)
    _commit(temp_git_repo, "novo.txt", "da principal\n", "main")
    subprocess.run(["git", "checkout", "feature/a"], cwd=temp_git_repo, check=True, capture_output=True)

    code, _ = await adapter.sync_branch(temp_git_repo, "main")

    assert code == 0
    assert os.path.exists(os.path.join(temp_git_repo, "novo.txt"))


@pytest.mark.asyncio
async def test_sync_branch_aborts_on_conflict(temp_git_repo: str):
    adapter = GitCliAdapter()
    _conflicting_branches(temp_git_repo)

    code, out = await adapter.sync_branch(temp_git_repo, "main")

    assert code != 0 and "CONFLICT" in out
    assert await adapter.has_changes(temp_git_repo) is False
    assert await adapter.current_branch(temp_git_repo) == "feature/a"
