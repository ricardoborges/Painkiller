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



@pytest.mark.asyncio
async def test_push_keeps_credentials_out_of_git_config():
    import base64
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = GitCliAdapter(http_credentials={"http://gitea:3000/": ("painkiller", "s3cret")})
        await adapter.init_repo(tmpdir, default_branch="main", initial_commit=True)
        # Remote no formato antigo, com a senha embutida.
        await adapter.set_remote(tmpdir, "http://painkiller:s3cret@gitea:3000/alice/loja.git")

        calls = []
        real_run = adapter._run_git

        async def spy(repo_path, *args, env=None):
            if args and args[0] == "push":
                calls.append((args, env))
                return 0, "", ""
            return await real_run(repo_path, *args, env=env)

        with patch.object(adapter, "_run_git", side_effect=spy):
            code, _ = await adapter.push(tmpdir, "main")

        assert code == 0
        with open(os.path.join(tmpdir, ".git", "config"), encoding="utf-8") as f:
            assert "s3cret" not in f.read()

        (args, env), = calls
        assert "s3cret" not in " ".join(args)
        token = base64.b64encode(b"painkiller:s3cret").decode("ascii")
        assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
        assert env["GIT_CONFIG_VALUE_0"] == f"Authorization: Basic {token}"


@pytest.mark.asyncio
async def test_push_to_unknown_remote_gets_no_credentials():
    from painkiller.adapters.git.git_adapter import strip_userinfo

    adapter = GitCliAdapter(http_credentials={"http://gitea:3000": ("painkiller", "s3cret")})
    assert adapter._auth_env("https://github.com/alice/loja.git") is None
    # Prefixo precisa terminar em fronteira de caminho.
    assert adapter._auth_env("http://gitea:30001/alice/loja.git") is None
    assert strip_userinfo("http://u:p@gitea:3000/a/b.git") == "http://gitea:3000/a/b.git"
    assert strip_userinfo("git@github.com:a/b.git") == "git@github.com:a/b.git"


@pytest.mark.asyncio
async def test_delete_branch_removes_merged_branch_locally_and_on_remote():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = os.path.join(tmpdir, "repo")
        remote = os.path.join(tmpdir, "remote.git")
        adapter = GitCliAdapter()
        await adapter._run_git(tmpdir, "init", "--bare", remote)
        await adapter.init_repo(repo, default_branch="main", initial_commit=True)
        await adapter.set_remote(repo, remote)
        await adapter.push(repo, "main")

        for name in ("feature/merged", "feature/pending"):
            await adapter.create_branch(repo, name, base_branch="main")
            with open(os.path.join(repo, name.replace("/", "-") + ".txt"), "w") as f:
                f.write(name)
            await adapter.commit_wip(repo, f"feat: {name}")
            await adapter.push(repo, name)
            await adapter.switch_branch(repo, "main")
        await adapter.merge_branch(repo, source_branch="feature/merged", target_branch="main")

        code, out = await adapter.delete_branch(repo, "feature/merged", merged_into="main")
        assert code == 0, out
        # Uma branch não incorporada nunca é apagada: perderia trabalho
        code, _ = await adapter.delete_branch(repo, "feature/pending", merged_into="main")
        assert code != 0

        _, local, _ = await adapter._run_git(repo, "branch", "--list")
        _, remote_heads, _ = await adapter._run_git(remote, "branch", "--list")
        assert "feature/merged" not in local and "feature/pending" in local
        assert "feature/merged" not in remote_heads and "feature/pending" in remote_heads
