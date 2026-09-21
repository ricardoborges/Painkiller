"""Git CLI Adapter implementing GitPort."""

import asyncio
import os
from typing import Optional
from painkiller.core.ports.git import GitPort


class GitCliAdapter(GitPort):
    """Asynchronous Git operations executing git CLI commands."""

    async def _run_git(self, repo_path: str, *args: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (
            proc.returncode if proc.returncode is not None else 1,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def create_branch(self, repo_path: str, branch_name: str, base_branch: str = "main") -> None:
        # First ensure we are on base branch or fetch latest
        code, _, _ = await self._run_git(repo_path, "checkout", branch_name)
        if code != 0:
            # Create new branch
            create_code, _, err = await self._run_git(repo_path, "checkout", "-b", branch_name, base_branch)
            if create_code != 0:
                raise RuntimeError(f"Failed to create git branch {branch_name} from {base_branch}: {err}")

    async def commit_wip(self, repo_path: str, message: str) -> str:
        await self._run_git(repo_path, "add", "-A")
        code, out, err = await self._run_git(repo_path, "commit", "-m", message)
        # Even if nothing to commit, return current HEAD
        code_rev, out_rev, _ = await self._run_git(repo_path, "rev-parse", "HEAD")
        return out_rev.strip()

    async def get_diff(self, repo_path: str, base_branch: str = "main") -> str:
        code, out, _ = await self._run_git(repo_path, "diff", f"{base_branch}...HEAD")
        if not out.strip():
            # Try plain diff if not committed or branches identical
            _, out, _ = await self._run_git(repo_path, "diff", base_branch)
        return out

    async def has_changes(self, repo_path: str) -> bool:
        code, out, _ = await self._run_git(repo_path, "status", "--porcelain")
        return bool(out.strip())

    async def run_tests(self, repo_path: str, test_command: Optional[str] = None) -> tuple[int, str]:
        cmd = test_command or "pytest"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace") + "\n" + stderr.decode("utf-8", errors="replace")
        return (proc.returncode if proc.returncode is not None else 1, output)

    async def init_repo(self, repo_path: str, default_branch: str = "main", initial_commit: bool = True) -> None:
        os.makedirs(repo_path, exist_ok=True)
        git_dir = os.path.join(repo_path, ".git")
        if not os.path.exists(git_dir):
            code, _, err = await self._run_git(repo_path, "init", "-b", default_branch)
            if code != 0:
                # Older git versions might not support -b in init
                await self._run_git(repo_path, "init")
                await self._run_git(repo_path, "checkout", "-b", default_branch)

        # Configure local committer identity so commits never fail
        await self._run_git(repo_path, "config", "user.name", "Painkiller Bot")
        await self._run_git(repo_path, "config", "user.email", "bot@painkiller.local")

        if initial_commit:
            readme_path = os.path.join(repo_path, "README.md")
            if not os.path.exists(readme_path):
                with open(readme_path, "w", encoding="utf-8") as f:
                    f.write("# Project\n\nGenerated and managed by Painkiller.\n")

            gitignore_path = os.path.join(repo_path, ".gitignore")
            if not os.path.exists(gitignore_path):
                with open(gitignore_path, "w", encoding="utf-8") as f:
                    f.write("__pycache__/\n*.pyc\nnode_modules/\n.env\n.DS_Store\n")

            has_c = await self.has_changes(repo_path)
            if has_c:
                await self._run_git(repo_path, "add", "-A")
                await self._run_git(repo_path, "commit", "-m", "Initial commit")

    async def set_remote(self, repo_path: str, remote_url: str, remote_name: str = "origin") -> None:
        code, _, _ = await self._run_git(repo_path, "remote", "get-url", remote_name)
        if code == 0:
            await self._run_git(repo_path, "remote", "set-url", remote_name, remote_url)
        else:
            await self._run_git(repo_path, "remote", "add", remote_name, remote_url)

    async def push(
        self,
        repo_path: str,
        branch_name: str,
        remote_name: str = "origin",
        set_upstream: bool = True,
    ) -> tuple[int, str]:
        args = ["push"]
        if set_upstream:
            args.extend(["-u", remote_name, branch_name])
        else:
            args.extend([remote_name, branch_name])
        code, out, err = await self._run_git(repo_path, *args)
        return code, (out + "\n" + err).strip()

    async def merge_branch(
        self,
        repo_path: str,
        source_branch: str,
        target_branch: str = "main",
    ) -> tuple[int, str]:
        code, _, err = await self._run_git(repo_path, "checkout", target_branch)
        if code != 0:
            return code, f"Failed to checkout {target_branch}: {err}".strip()
        code_merge, out, err_m = await self._run_git(
            repo_path,
            "merge",
            "--no-ff",
            "-m",
            f"Merge branch '{source_branch}' into {target_branch}",
            source_branch,
        )
        return code_merge, (out + "\n" + err_m).strip()

