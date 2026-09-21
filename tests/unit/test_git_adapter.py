"""Unit tests for GitCliAdapter."""

import os
import tempfile
import pytest
from painkiller.adapters.git.git_adapter import GitCliAdapter


@pytest.mark.asyncio
async def test_git_init_and_commit():
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = GitCliAdapter()
        await adapter.init_repo(tmpdir, default_branch="main", initial_commit=True)

        assert os.path.exists(os.path.join(tmpdir, ".git"))
        assert os.path.exists(os.path.join(tmpdir, "README.md"))
        assert os.path.exists(os.path.join(tmpdir, ".gitignore"))

        has_c = await adapter.has_changes(tmpdir)
        assert not has_c, "All files should be committed initially"

        # Create branch
        await adapter.create_branch(tmpdir, "feature/test-1", base_branch="main")

        # Create a new file and commit WIP
        new_file = os.path.join(tmpdir, "test.txt")
        with open(new_file, "w") as f:
            f.write("hello world")

        assert await adapter.has_changes(tmpdir)
        sha = await adapter.commit_wip(tmpdir, "feat: add test.txt")
        assert len(sha) == 40

        # Diff against main
        diff = await adapter.get_diff(tmpdir, base_branch="main")
        assert "test.txt" in diff

        # Merge branch into main
        code, out = await adapter.merge_branch(tmpdir, source_branch="feature/test-1", target_branch="main")
        assert code == 0
