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


@pytest.mark.asyncio
async def test_push_retries_transient_failures_but_not_rejections():
    from unittest.mock import patch

    adapter = GitCliAdapter()
    adapter.push_retry_delays = (0, 0)
    results = [(128, "", "fatal: unable to access 'http://gitea:3000/': Connection refused"), (0, "ok", "")]

    async def flaky(repo_path, *args, env=None):
        if args[0] == "push":
            return results.pop(0)
        return 1, "", ""

    with patch.object(adapter, "_run_git", side_effect=flaky):
        code, _ = await adapter.push("/repo", "feature/t1")
    assert code == 0

    calls = []

    async def rejected(repo_path, *args, env=None):
        if args[0] == "push":
            calls.append(args)
            return 1, "", " ! [rejected]        main -> main (non-fast-forward)"
        return 1, "", ""

    with patch.object(adapter, "_run_git", side_effect=rejected):
        code, _ = await adapter.push("/repo", "main")
    assert code == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_branch_changes_live_includes_uncommitted_and_untracked():
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = GitCliAdapter()
        await adapter.init_repo(tmpdir, default_branch="main", initial_commit=True)
        await adapter.create_branch(tmpdir, "feature/t1", base_branch="main")

        with open(os.path.join(tmpdir, "committed.py"), "w") as f:
            f.write("a = 1\n")
        await adapter.commit_wip(tmpdir, "wip")
        # Alterado sem commit, e um arquivo novo que nem entrou no índice.
        with open(os.path.join(tmpdir, "committed.py"), "a") as f:
            f.write("b = 2\n")
        os.makedirs(os.path.join(tmpdir, "src"))
        with open(os.path.join(tmpdir, "src", "novo arquivo.ts"), "w") as f:
            f.write("export const x = 1;\n+++ não é cabeçalho\n")
        with open(os.path.join(tmpdir, "logo.png"), "wb") as f:
            f.write(b"\x89PNG\x00\x00binary")

        changes = await adapter.branch_changes(tmpdir, "feature/t1", base_branch="main")

        assert changes.available and changes.live
        files = {c.path: c for c in changes.files}
        assert files["committed.py"].status == "A"
        assert files["committed.py"].additions == 2
        assert "+b = 2" in files["committed.py"].patch
        assert files["src/novo arquivo.ts"].additions == 2
        assert files["src/novo arquivo.ts"].patch.startswith("@@ -0,0 +1,2 @@")
        assert files["logo.png"].binary and files["logo.png"].patch is None
        # A leitura não pode deixar lock para trás nem mexer no índice.
        assert not os.path.exists(os.path.join(tmpdir, ".git", "index.lock"))
        assert "src/novo arquivo.ts" not in (await adapter._run_git(tmpdir, "diff", "--cached", "--name-only"))[1]


@pytest.mark.asyncio
async def test_branch_changes_of_branch_not_checked_out():
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = GitCliAdapter()
        await adapter.init_repo(tmpdir, default_branch="main", initial_commit=True)
        await adapter.create_branch(tmpdir, "feature/t2", base_branch="main")
        os.remove(os.path.join(tmpdir, "README.md"))
        with open(os.path.join(tmpdir, ".gitignore"), "a") as f:
            f.write("dist/\n")
        await adapter.commit_wip(tmpdir, "wip")
        await adapter.switch_branch(tmpdir, "main")
        # Sujeira no checkout atual não pertence à tarefa.
        with open(os.path.join(tmpdir, "stray.txt"), "w") as f:
            f.write("x")

        changes = await adapter.branch_changes(tmpdir, "feature/t2", base_branch="main")

        assert changes.available and not changes.live
        files = {c.path: c for c in changes.files}
        assert set(files) == {"README.md", ".gitignore"}
        assert files["README.md"].status == "D"
        assert files[".gitignore"].status == "M" and files[".gitignore"].additions == 1


@pytest.mark.asyncio
async def test_branch_changes_after_merge_and_after_branch_deleted():
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = GitCliAdapter()
        await adapter.init_repo(tmpdir, default_branch="main", initial_commit=True)
        await adapter.create_branch(tmpdir, "feature/t3", base_branch="main")
        with open(os.path.join(tmpdir, "task.py"), "w") as f:
            f.write("x = 1\n")
        await adapter.commit_wip(tmpdir, "wip")
        code, _ = await adapter.merge_branch(tmpdir, "feature/t3", "main")
        assert code == 0

        # Incorporada, o merge-base é a própria ponta: o diff vem do merge.
        changes = await adapter.branch_changes(tmpdir, "feature/t3", base_branch="main")
        assert changes.available and changes.merged and changes.merge_commit
        assert [c.path for c in changes.files] == ["task.py"]

        # Fechada a sessão, a branch some, mas o diff continua legível.
        await adapter._run_git(tmpdir, "branch", "-D", "feature/t3")
        changes = await adapter.branch_changes(tmpdir, "feature/t3", base_branch="main")
        assert changes.available and changes.merged
        assert [c.path for c in changes.files] == ["task.py"]


@pytest.mark.asyncio
async def test_branch_changes_missing_branch():
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = GitCliAdapter()
        await adapter.init_repo(tmpdir, default_branch="main", initial_commit=True)
        changes = await adapter.branch_changes(tmpdir, "feature/never", base_branch="main")
        assert changes.available is False and changes.files == []


def test_split_patch_caps_and_paths():
    from painkiller.adapters.git.git_adapter import split_patch

    patch = (
        "diff --git a/x y.txt b/x y.txt\n"
        "index 1..2 100644\n"
        "--- a/x y.txt\t\n"
        "+++ b/x y.txt\t\n"
        "@@ -1 +1,2 @@\n"
        "-old\n"
        "+new\n"
        "+++plus\n"
        "diff --git a/img.bin b/img.bin\n"
        "Binary files a/img.bin and b/img.bin differ\n"
    )
    files = split_patch(patch)
    assert [f.path for f in files] == ["x y.txt", "img.bin"]
    assert (files[0].additions, files[0].deletions) == (2, 1)
    assert files[0].patch.startswith("@@")
    assert files[1].binary and files[1].patch is None
