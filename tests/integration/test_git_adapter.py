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
