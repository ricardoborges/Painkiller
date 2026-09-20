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
