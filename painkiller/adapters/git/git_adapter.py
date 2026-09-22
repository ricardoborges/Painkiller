"""Git CLI Adapter implementing GitPort."""

import asyncio
import base64
import os
import urllib.parse
from typing import Optional
from painkiller.core.ports.git import GitPort


def strip_userinfo(url: str) -> str:
    """Drop ``user:password@`` from an http(s) URL; other URLs pass through."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or "@" not in parsed.netloc:
        return url
    return urllib.parse.urlunsplit(parsed._replace(netloc=parsed.netloc.rsplit("@", 1)[1]))


class GitCliAdapter(GitPort):
    """Asynchronous Git operations executing git CLI commands.

    ``http_credentials`` maps a remote URL prefix to ``(user, password)``. The
    credential reaches git only through the environment of the push process,
    never ``.git/config``: the repo is bind-mounted into the agent containers,
    so anything stored there is readable by the agent.
    """

    def __init__(self, http_credentials: Optional[dict[str, tuple[str, str]]] = None):
        self.http_credentials = {
            prefix.rstrip("/"): cred
            for prefix, cred in (http_credentials or {}).items()
            if prefix and cred and cred[1]
        }

    async def _run_git(self, repo_path: str, *args: str, env: Optional[dict[str, str]] = None) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        return (
            proc.returncode if proc.returncode is not None else 1,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    def _ensure_painkiller_excluded(self, repo_path: str) -> None:
        exclude_path = os.path.join(repo_path, ".git", "info", "exclude")
        if os.path.exists(exclude_path):
            try:
                with open(exclude_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if ".painkiller" not in content:
                    with open(exclude_path, "a", encoding="utf-8") as f:
                        f.write("\n.painkiller/\n")
            except Exception:
                pass

    async def create_branch(self, repo_path: str, branch_name: str, base_branch: str = "main") -> None:
        self._ensure_painkiller_excluded(repo_path)
        # First ensure we are on base branch or fetch latest
        code, _, _ = await self._run_git(repo_path, "checkout", branch_name)
        if code != 0:
            # Create new branch
            create_code, _, err = await self._run_git(repo_path, "checkout", "-b", branch_name, base_branch)
            if create_code != 0:
                raise RuntimeError(f"Failed to create git branch {branch_name} from {base_branch}: {err}")

    async def commit_wip(self, repo_path: str, message: str) -> str:
        self._ensure_painkiller_excluded(repo_path)
        # Untrack .painkiller if it was accidentally tracked in index
        _, out_pk, _ = await self._run_git(repo_path, "ls-files", ".painkiller")
        if out_pk.strip():
            await self._run_git(repo_path, "rm", "-r", "--cached", "--ignore-unmatch", ".painkiller")

        # If no tracked or untracked changes, skip committing
        _, status_out, _ = await self._run_git(repo_path, "status", "--porcelain")
        if not status_out.strip():
            _, out_rev, _ = await self._run_git(repo_path, "rev-parse", "HEAD")
            return out_rev.strip()

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
        code = proc.returncode if proc.returncode is not None else 1
        # Pytest exit code 5: No tests were collected (e.g. web/HTML/JS repos)
        if code == 5 and ("collected 0 items" in output or "no tests ran" in output or not test_command):
            return (0, output + "\n(Sem testes coletados no repositório — aprovado por padrão)")
        return (code, output)

    async def init_repo(self, repo_path: str, default_branch: str = "main", initial_commit: bool = True) -> None:
        os.makedirs(repo_path, exist_ok=True)
        git_dir = os.path.join(repo_path, ".git")
        if not os.path.exists(git_dir):
            code, _, err = await self._run_git(repo_path, "init", "-b", default_branch)
            if code != 0:
                # Older git versions might not support -b in init
                await self._run_git(repo_path, "init")
                await self._run_git(repo_path, "checkout", "-b", default_branch)

        self._ensure_painkiller_excluded(repo_path)

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
                    f.write("__pycache__/\n*.pyc\nnode_modules/\n.env\n.DS_Store\n.painkiller/\n")

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
        remote_url = await self.scrub_remote_credentials(repo_path, remote_name)
        args = ["push"]
        if set_upstream:
            args.extend(["-u", remote_name, branch_name])
        else:
            args.extend([remote_name, branch_name])
        code, out, err = await self._run_git(repo_path, *args, env=self._auth_env(remote_url))
        return code, (out + "\n" + err).strip()

    async def scrub_remote_credentials(self, repo_path: str, remote_name: str = "origin") -> Optional[str]:
        """Rewrite a remote that still carries ``user:password@``; return the clean URL.

        Repositórios criados antes desta mudança guardavam a senha da conta de
        serviço no `.git/config`, legível pelo agente dentro do contêiner.
        """
        code, out, _ = await self._run_git(repo_path, "remote", "get-url", remote_name)
        if code != 0:
            return None
        url = out.strip()
        clean = strip_userinfo(url)
        if clean != url:
            await self._run_git(repo_path, "remote", "set-url", remote_name, clean)
        return clean

    def _auth_env(self, remote_url: Optional[str]) -> Optional[dict[str, str]]:
        if not remote_url:
            return None
        for prefix, (user, password) in self.http_credentials.items():
            if remote_url.startswith(prefix + "/"):
                token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
                # GIT_CONFIG_* (git >= 2.31) vale só para este processo e não
                # aparece na linha de comando.
                return {
                    **os.environ,
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "http.extraHeader",
                    "GIT_CONFIG_VALUE_0": f"Authorization: Basic {token}",
                }
        return None

    async def commit_paths(self, repo_path: str, paths: list[str], message: str) -> Optional[str]:
        existing = [p for p in paths if os.path.exists(os.path.join(repo_path, p))]
        if not existing:
            return None
        await self._run_git(repo_path, "add", "-A", "--", *existing)
        # Exit 0 em `diff --cached --quiet` = nada preparado nesses caminhos.
        code, _, _ = await self._run_git(repo_path, "diff", "--cached", "--quiet", "--", *existing)
        if code == 0:
            return None
        # O pathspec no commit garante que só estes caminhos entram, mesmo que
        # haja outras mudanças preparadas no índice.
        code, _, err = await self._run_git(repo_path, "commit", "-m", message, "--", *existing)
        if code != 0:
            raise RuntimeError(f"Failed to commit {existing}: {err}")
        _, out_rev, _ = await self._run_git(repo_path, "rev-parse", "HEAD")
        return out_rev.strip()

    async def switch_branch(self, repo_path: str, branch_name: str) -> tuple[int, str]:
        self._ensure_painkiller_excluded(repo_path)
        if await self.current_branch(repo_path) == branch_name:
            return 0, ""
        # Só arquivos rastreados: não rastreados (como .painkiller/) atravessam o
        # checkout sem dano, mas uma edição pendente de tarefa iria junto para a
        # branch de destino.
        _, dirty, _ = await self._run_git(repo_path, "status", "--porcelain", "--untracked-files=no")
        if dirty.strip():
            return 1, f"Alterações não commitadas impedem a troca para {branch_name}:\n{dirty.strip()}"
        code, out, err = await self._run_git(repo_path, "checkout", branch_name)
        return code, (out + "\n" + err).strip()

    async def current_branch(self, repo_path: str) -> str:
        _, out, _ = await self._run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        return out.strip()

    async def merge_branch(
        self,
        repo_path: str,
        source_branch: str,
        target_branch: str = "main",
    ) -> tuple[int, str]:
        self._ensure_painkiller_excluded(repo_path)
        # Untrack .painkiller if it was accidentally tracked in index
        _, out_pk, _ = await self._run_git(repo_path, "ls-files", ".painkiller")
        if out_pk.strip():
            await self._run_git(repo_path, "rm", "-r", "--cached", "--ignore-unmatch", ".painkiller")

        lock_file = os.path.join(repo_path, ".git", "index.lock")
        code, _, err = await self._run_git(repo_path, "checkout", target_branch)
        if code != 0:
            if "index.lock" in err:
                await asyncio.sleep(0.5)
                if os.path.exists(lock_file):
                    try:
                        os.remove(lock_file)
                    except OSError:
                        pass
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

    async def archive(self, repo_path: str, ref: str = "HEAD") -> bytes:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "archive",
            "--format=zip",
            ref,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"git archive {ref} failed: {stderr.decode('utf-8', errors='replace').strip()}"
            )
        return stdout
