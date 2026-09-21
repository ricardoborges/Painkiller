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


@pytest.mark.asyncio
async def test_git_painkiller_excluded():
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = GitCliAdapter()
        await adapter.init_repo(tmpdir, default_branch="main", initial_commit=True)

        # Verify .painkiller/ is in .gitignore and .git/info/exclude
        with open(os.path.join(tmpdir, ".gitignore"), "r") as f:
            assert ".painkiller/" in f.read()

        exclude_file = os.path.join(tmpdir, ".git", "info", "exclude")
        with open(exclude_file, "r") as f:
            assert ".painkiller/" in f.read()

        # Create a file inside .painkiller
        pk_dir = os.path.join(tmpdir, ".painkiller")
        os.makedirs(pk_dir, exist_ok=True)
        with open(os.path.join(pk_dir, "test.db"), "w") as f:
            f.write("database binary data")

        # commit_wip should not commit .painkiller
        await adapter.commit_wip(tmpdir, "wip commit")
        has_c = await adapter.has_changes(tmpdir)
        assert not has_c

        # Create branch, write more to .painkiller, and verify merge works cleanly
        await adapter.create_branch(tmpdir, "feature/test-pk", base_branch="main")
        with open(os.path.join(tmpdir, "code.py"), "w") as f:
            f.write("print('ok')")
        with open(os.path.join(pk_dir, "test.db"), "w") as f:
            f.write("updated database binary data")

        await adapter.commit_wip(tmpdir, "feat: add code")
        diff = await adapter.get_diff(tmpdir, base_branch="main")
        assert "code.py" in diff
        assert "test.db" not in diff

        code, out = await adapter.merge_branch(tmpdir, source_branch="feature/test-pk", target_branch="main")
        assert code == 0

