"""Git CLI Adapter implementing GitPort."""

import asyncio
import base64
import os
import urllib.parse
from typing import Optional
from painkiller.core.domain.models import BranchChanges, FileChange
from painkiller.core.ports.git import GitPort

#: Tetos de `branch_changes`: um package-lock.json ou uma pasta gerada sem
#: .gitignore não podem virar megabytes na tela.
CHANGES_MAX_FILES = 300
CHANGES_MAX_FILE_BYTES = 64 * 1024
CHANGES_MAX_TOTAL_BYTES = 1024 * 1024


def strip_userinfo(url: str) -> str:
    """Drop ``user:password@`` from an http(s) URL; other URLs pass through."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or "@" not in parsed.netloc:
        return url
    return urllib.parse.urlunsplit(parsed._replace(netloc=parsed.netloc.rsplit("@", 1)[1]))


def _patch_path(raw: str) -> str:
    """Path of a ``---``/``+++`` line, without the ``a/``/``b/`` prefix."""
    # O git acrescenta um TAB depois de nomes com espaço.
    raw = raw.rstrip("\n").rstrip("\t")
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        raw = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return raw[2:] if raw[:2] in ("a/", "b/") else raw


def _header_path(line: str) -> str:
    """Path of a ``diff --git a/X b/X`` line (binary and mode-only changes have no ---/+++)."""
    rest = line[len("diff --git "):].rstrip("\n")
    half = (len(rest) - 1) // 2
    if rest[half:half + 1] == " " and rest[2:half] == rest[half + 3:]:
        return rest[2:half]
    cut = rest.rfind(" b/")
    return _patch_path(rest[cut + 1:] if cut > 0 else rest)


def split_patch(text: str) -> list[FileChange]:
    """Split a ``git diff`` into one FileChange per file; the patch keeps only the hunks."""
    files: list[FileChange] = []
    current: Optional[FileChange] = None
    hunks: list[str] = []
    in_hunk = False

    def flush() -> None:
        if current is not None:
            current.patch = "".join(hunks) or None
            files.append(current)

    for line in text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            flush()
            current, hunks, in_hunk = FileChange(path=_header_path(line)), [], False
            continue
        if current is None:
            continue
        if line.startswith("@@"):
            in_hunk = True
            hunks.append(line)
        elif in_hunk:
            # Dentro do hunk, "+++" ou "---" é conteúdo, não cabeçalho.
            hunks.append(line)
            if line.startswith("+"):
                current.additions += 1
            elif line.startswith("-"):
                current.deletions += 1
        elif line.startswith("new file mode"):
            current.status = "A"
        elif line.startswith("deleted file mode"):
            current.status = "D"
        elif line.startswith("+++ ") and line[4:].strip() != "/dev/null":
            current.path = _patch_path(line[4:])
        elif line.startswith("--- ") and line[4:].strip() != "/dev/null" and current.status == "D":
            current.path = _patch_path(line[4:])
        elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            current.binary = True
    flush()
    return files


def _untracked_change(repo_path: str, path: str) -> FileChange:
    """A file the agent created and has not committed yet, as an all-added patch."""
    change = FileChange(path=path, status="A")
    full = os.path.join(repo_path, path)
    if os.path.isdir(full):
        # Repositório aninhado: o ls-files mostra só a pasta.
        return change
    try:
        with open(full, "rb") as f:
            data = f.read(CHANGES_MAX_FILE_BYTES + 1)
    except OSError:
        return change
    if b"\0" in data[:8000]:
        change.binary = True
        return change
    if len(data) > CHANGES_MAX_FILE_BYTES:
        data = data[:CHANGES_MAX_FILE_BYTES]
        change.truncated = True
    lines = data.decode("utf-8", errors="replace").splitlines()
    change.additions = len(lines)
    if lines:
        change.patch = f"@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{line}\n" for line in lines)
    return change


def _is_permanent_push_error(output: str) -> bool:
    """A rejection that retrying cannot fix (history diverged, hook refused)."""
    text = output.lower()
    return any(s in text for s in ("[rejected]", "non-fast-forward", "pre-receive hook declined", "protected branch"))


class GitCliAdapter(GitPort):
    """Asynchronous Git operations executing git CLI commands.

    ``http_credentials`` maps a remote URL prefix to ``(user, password)``. The
    credential reaches git only through the environment of the push process,
    never ``.git/config``: the repo is bind-mounted into the agent containers,
    so anything stored there is readable by the agent.
    """

    #: Pausas (s) entre as tentativas de push; os testes zeram.
    push_retry_delays: tuple[float, ...] = (2.0, 5.0)

    def __init__(self, http_credentials: Optional[dict[str, tuple[str, str]]] = None):
        self.set_http_credentials(http_credentials)

    def set_http_credentials(self, http_credentials: Optional[dict[str, tuple[str, str]]]) -> None:
        """Replace the push credentials (the Gitea password is installed after startup)."""
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
        env = self._auth_env(remote_url)
        # O Gitea some por alguns segundos quando reinicia (sync_gitea_root_url,
        # restart do compose). Sem nova tentativa, o push da branch da tarefa
        # falhava calado e o "Testar" do Coolify não achava a branch.
        for delay in (*self.push_retry_delays, None):
            code, out, err = await self._run_git(repo_path, *args, env=env)
            output = (out + "\n" + err).strip()
            if code == 0 or delay is None or _is_permanent_push_error(output):
                return code, output
            await asyncio.sleep(delay)
        return code, output

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

    async def delete_branch(
        self,
        repo_path: str,
        branch_name: str,
        merged_into: str = "main",
        remote_name: str = "origin",
    ) -> tuple[int, str]:
        if branch_name == merged_into:
            return 1, f"Recusado: {branch_name} é a branch de destino"

        code, _, _ = await self._run_git(repo_path, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch_name}")
        local_exists = code == 0
        if local_exists:
            # Só apaga o que já está incorporado: uma branch com commits fora do
            # merge perderia trabalho.
            code, _, _ = await self._run_git(repo_path, "merge-base", "--is-ancestor", branch_name, merged_into)
            if code != 0:
                return 1, f"{branch_name} não está incorporada em {merged_into}"
            if await self.current_branch(repo_path) == branch_name:
                code, out = await self.switch_branch(repo_path, merged_into)
                if code != 0:
                    return code, out
            code, _, err = await self._run_git(repo_path, "branch", "-D", branch_name)
            if code != 0:
                return code, err.strip()

        remote_url = await self.scrub_remote_credentials(repo_path, remote_name)
        if not remote_url:
            return 0, ""
        code, out, err = await self._run_git(
            repo_path, "push", remote_name, "--delete", branch_name, env=self._auth_env(remote_url)
        )
        output = (out + "\n" + err).strip()
        if code != 0 and "remote ref does not exist" in output:
            return 0, output
        return code, output

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

    async def _find_merge(self, repo_path: str, branch: str, base_branch: str) -> Optional[tuple[str, str, str]]:
        """The `merge_branch` commit of `branch` on `base_branch`: (sha, first parent, second parent)."""
        code, out, _ = await self._run_git(
            repo_path, "--no-optional-locks", "log", base_branch, "--merges", "--first-parent",
            "--fixed-strings", f"--grep=Merge branch '{branch}' into", "--format=%H %P", "-n", "1",
        )
        parts = out.split() if code == 0 else []
        return (parts[0], parts[1], parts[2]) if len(parts) >= 3 else None

    async def branch_changes(self, repo_path: str, branch: str, base_branch: str = "main") -> BranchChanges:
        result = BranchChanges(branch=branch, base_branch=base_branch)

        async def git(*args: str) -> tuple[int, str, str]:
            # Sem locks opcionais: o agente pode estar commitando neste repo agora.
            return await self._run_git(repo_path, "--no-optional-locks", "-c", "core.quotepath=off", *args)

        code, out, _ = await git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        tip = out.strip() if code == 0 else None

        # Depois do merge (--no-ff) o merge-base com a principal é a própria
        # ponta da branch e o diff sairia vazio: usa os pais do commit de merge.
        merge = await self._find_merge(repo_path, branch, base_branch)
        if merge and (tip is None or tip == merge[2]):
            sha, first, second = merge
            code, out, _ = await git("merge-base", first, second)
            base = out.strip() if code == 0 and out.strip() else first
            target = [base, second]
            result.merged = True
            result.merge_commit = sha
        elif tip is None:
            result.available = False
            return result
        else:
            code, out, _ = await git("merge-base", base_branch, branch)
            base = out.strip() if code == 0 and out.strip() else base_branch
            result.live = (await self.current_branch(repo_path)) == branch
            # Em checkout, compara com a árvore de trabalho: entra o que o agente
            # ainda não commitou.
            target = [base] if result.live else [base, branch]

        _, patch, _ = await git("diff", "--no-color", "--no-renames", "--no-ext-diff", *target, "--")
        changes = split_patch(patch)
        untracked: list[str] = []
        if result.live:
            _, out, _ = await git("ls-files", "--others", "--exclude-standard", "-z")
            untracked = [p for p in out.split("\0") if p]

        room = max(0, CHANGES_MAX_FILES - len(changes))
        changes.extend(
            await asyncio.to_thread(lambda: [_untracked_change(repo_path, p) for p in untracked[:room]])
        )
        result.omitted = max(0, len(changes) - CHANGES_MAX_FILES) + max(0, len(untracked) - room)
        changes = changes[:CHANGES_MAX_FILES]

        total = 0
        for change in changes:
            if not change.patch:
                continue
            if len(change.patch) > CHANGES_MAX_FILE_BYTES:
                cut = change.patch.rfind("\n", 0, CHANGES_MAX_FILE_BYTES)
                change.patch = change.patch[: cut + 1 if cut > 0 else CHANGES_MAX_FILE_BYTES]
                change.truncated = True
            if total + len(change.patch) > CHANGES_MAX_TOTAL_BYTES:
                change.patch = None
                change.truncated = True
                continue
            total += len(change.patch)
        result.files = sorted(changes, key=lambda c: c.path)
        return result
