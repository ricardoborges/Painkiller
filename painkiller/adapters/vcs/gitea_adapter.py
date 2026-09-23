"""Gitea VCS Adapter for managing remote git repositories."""

import asyncio
import logging
import os
import re
import secrets
import unicodedata
import urllib.parse
from typing import Optional, Any
import httpx
import docker

logger = logging.getLogger(__name__)

#: Nome da fonte de autenticação OAuth2 criada no Gitea para o login Google.
GOOGLE_AUTH_SOURCE = "google"
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"


class GiteaAdapter:
    """Asynchronous client for interacting with self-hosted Gitea/Forgejo instance."""

    def __init__(
        self,
        internal_base_url: Optional[str] = None,
        external_base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        email: Optional[str] = None,
        container_name: Optional[str] = None,
        docker_client: Optional[Any] = None,
    ):
        self.internal_base_url = (
            internal_base_url
            or os.environ.get("PAINKILLER_GITEA_INTERNAL_URL", "http://gitea:3000")
        ).rstrip("/")
        self.external_base_url = (
            external_base_url
            or os.environ.get("PAINKILLER_GITEA_EXTERNAL_URL", "http://localhost:8000/gitea")
        ).rstrip("/")
        self.username = username or os.environ.get("PAINKILLER_GITEA_USER", "painkiller")
        # Sem valor padrão: a conta de serviço é admin do site e o Gitea fica
        # exposto no host, então uma senha conhecida abriria todos os repos.
        self.password = password or os.environ.get("PAINKILLER_GITEA_PASSWORD", "")
        self.email = email or os.environ.get("PAINKILLER_GITEA_EMAIL", "bot@painkiller.local")
        self.container_name = container_name or os.environ.get("PAINKILLER_GITEA_CONTAINER_NAME", "painkiller-gitea")
        self._docker_client = docker_client
        # Id da fonte OAuth "google" no Gitea, descoberto uma vez por processo.
        self._google_source_id: Optional[int] = None

    @property
    def docker_client(self):
        if self._docker_client is None:
            try:
                self._docker_client = docker.from_env()
            except Exception as e:
                logger.debug(f"Docker client not available in GiteaAdapter: {e}")
                self._docker_client = None
        return self._docker_client

    def _auth(self) -> tuple[str, str]:
        return (self.username, self.password)

    def push_credentials(self) -> dict[str, tuple[str, str]]:
        """Credentials for pushing to this Gitea, keyed by the internal URL prefix."""
        return {self.internal_base_url: self._auth()}

    @staticmethod
    def slugify_name(name: str) -> str:
        """Convert a project name to a valid Gitea repository name."""
        # O Gitea só aceita [A-Za-z0-9_.-]: "Gestão" precisa virar "gestao".
        ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
        cleaned = re.sub(r"[^\w\s-]", "", ascii_name).strip().lower()
        slug = re.sub(r"[-\s]+", "-", cleaned)
        return slug or "project"

    async def is_available(self, timeout: float = 3.0) -> bool:
        """Check if Gitea HTTP service is reachable."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.get(f"{self.internal_base_url}/api/v1/version")
                return res.status_code == 200
        except Exception:
            return False

    async def ensure_admin_user(self) -> bool:
        """Verify the service account exists; if not, create it via container CLI."""
        # 1. Test basic auth against /api/v1/user
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(
                    f"{self.internal_base_url}/api/v1/user",
                    auth=self._auth(),
                )
                if res.status_code == 200:
                    return True
        except Exception as e:
            logger.debug(f"Gitea auth test failed: {e}")

        # 2. Attempt to create admin user via Docker container exec if possible
        if self.docker_client:
            loop = asyncio.get_running_loop()
            try:
                def _exec_create():
                    try:
                        container = self.docker_client.containers.get(self.container_name)
                        # O CLI do Gitea recusa rodar como root, e `su git` já como
                        # git pede senha: executa direto como git. Lista em vez de
                        # string para a senha não passar por shell nenhum.
                        exit_code, output = container.exec_run(
                            [
                                "gitea", "admin", "user", "create", "--admin",
                                "--username", self.username,
                                "--password", self.password,
                                "--email", self.email,
                                "--must-change-password=false",
                            ],
                            user="git",
                        )
                        if exit_code != 0 and b"already exists" in (output or b""):
                            # Usuário existe com outra senha: alinha com a do .env.
                            exit_code, output = container.exec_run(
                                [
                                    "gitea", "admin", "user", "change-password",
                                    "--username", self.username,
                                    "--password", self.password,
                                    "--must-change-password=false",
                                ],
                                user="git",
                            )
                        logger.info(f"Gitea user creation output: code={exit_code}, out={output}")
                        return exit_code == 0
                    except Exception as ex:
                        logger.warning(f"Could not exec into {self.container_name}: {ex}")
                        return False

                created = await loop.run_in_executor(None, _exec_create)
                if created:
                    return True
            except Exception as e:
                logger.warning(f"Error executing user creation in Gitea container: {e}")

        # Final check
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(
                    f"{self.internal_base_url}/api/v1/user",
                    auth=self._auth(),
                )
                return res.status_code == 200
        except Exception:
            return False

    @staticmethod
    def username_candidate(email: str) -> str:
        """Derive a valid Gitea login from the local part of an e-mail."""
        local = email.split("@", 1)[0].lower()
        slug = re.sub(r"[^a-z0-9]+", "-", local).strip("-")[:30].strip("-")
        return slug or "user"

    def _exec_in_container(self, command: list[str]) -> tuple[int, str]:
        container = self.docker_client.containers.get(self.container_name)
        exit_code, output = container.exec_run(command, user="git")
        return exit_code, (output or b"").decode("utf-8", errors="replace")

    async def ensure_google_auth_source(self, client_id: str, client_secret: str) -> Optional[int]:
        """Make sure Gitea has an OAuth2 source for Google and return its id.

        Com ela, o usuário entra no Gitea pelo mesmo Google do Painkiller e cai
        na conta que `ensure_user` criou (vinculada pelo `sub`). Só existe CLI
        para isso, então depende do socket Docker; sem ele devolve None e o
        Gitea fica sem SSO (o resto funciona).
        """
        if self._google_source_id is not None:
            return self._google_source_id
        if not client_id or not client_secret or not self.docker_client:
            return None

        def _ensure() -> Optional[int]:
            code, out = self._exec_in_container(["gitea", "admin", "auth", "list"])
            if code != 0:
                logger.warning(f"Could not list Gitea auth sources: {out}")
                return None
            source_id = self._find_auth_source(out, GOOGLE_AUTH_SOURCE)
            if source_id is not None:
                return source_id
            code, out = self._exec_in_container([
                "gitea", "admin", "auth", "add-oauth",
                "--name", GOOGLE_AUTH_SOURCE,
                "--provider", "openidConnect",
                "--key", client_id,
                "--secret", client_secret,
                "--auto-discover-url", GOOGLE_DISCOVERY_URL,
                "--scopes", "openid", "--scopes", "email", "--scopes", "profile",
            ])
            if code != 0:
                logger.warning(f"Could not create Gitea Google auth source: {out}")
                return None
            code, out = self._exec_in_container(["gitea", "admin", "auth", "list"])
            return self._find_auth_source(out, GOOGLE_AUTH_SOURCE) if code == 0 else None

        try:
            loop = asyncio.get_running_loop()
            self._google_source_id = await loop.run_in_executor(None, _ensure)
        except Exception as e:
            logger.warning(f"Error ensuring Gitea Google auth source: {e}")
        return self._google_source_id

    @staticmethod
    def _find_auth_source(listing: str, name: str) -> Optional[int]:
        """Parse `gitea admin auth list` (ID, Name, Type, Enabled columns)."""
        for line in listing.splitlines():
            cols = line.split()
            if len(cols) >= 2 and cols[0].isdigit() and cols[1] == name:
                return int(cols[0])
        return None

    async def ensure_user(
        self,
        email: str,
        full_name: str = "",
        oauth_source_id: Optional[int] = None,
        oauth_login_name: Optional[str] = None,
    ) -> str:
        """Create (or find) the Gitea account bound to a Painkiller user; return its login.

        A conta nasce privada e com senha aleatória que ninguém conhece: o acesso
        humano é pelo SSO do Google (quando `oauth_source_id` vem), e o Painkiller
        empurra código com a conta de serviço, que é admin do site.
        """
        base = self.username_candidate(email)
        users_url = f"{self.internal_base_url}/api/v1/admin/users"
        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(20):
                candidate = base if attempt == 0 else f"{base}-{attempt + 1}"
                payload: dict[str, Any] = {
                    "username": candidate,
                    "email": email,
                    "full_name": full_name,
                    "password": secrets.token_urlsafe(24),
                    "must_change_password": False,
                    "send_notify": False,
                    "visibility": "private",
                }
                if oauth_source_id and oauth_login_name:
                    payload["source_id"] = oauth_source_id
                    payload["login_name"] = oauth_login_name

                res = await client.post(users_url, json=payload, auth=self._auth())
                if res.status_code == 401:
                    await self.ensure_admin_user()
                    res = await client.post(users_url, json=payload, auth=self._auth())
                if res.status_code == 201:
                    return candidate
                if res.status_code != 422:
                    raise RuntimeError(f"Gitea user creation failed: {res.status_code} - {res.text}")

                # 422: login ocupado/reservado ou e-mail já cadastrado. Se a conta
                # com esse login é deste e-mail (banco do Painkiller perdido,
                # por exemplo), reaproveita em vez de criar outra.
                existing = await client.get(
                    f"{self.internal_base_url}/api/v1/users/{candidate}", auth=self._auth()
                )
                if existing.status_code == 200:
                    if (existing.json().get("email") or "").lower() == email.lower():
                        if oauth_source_id and oauth_login_name:
                            await client.patch(
                                f"{users_url}/{candidate}",
                                json={"source_id": oauth_source_id, "login_name": oauth_login_name},
                                auth=self._auth(),
                            )
                        return candidate
                elif "email" in res.text.lower():
                    # Login livre, mas o e-mail já pertence a outra conta do Gitea.
                    raise RuntimeError(f"Gitea already has another account for {email}: {res.text}")
        raise RuntimeError(f"No free Gitea username for {email}")

    async def create_repository(
        self,
        name: str,
        description: str = "",
        private: bool = True,
        owner: Optional[str] = None,
    ) -> dict[str, str]:
        """Create a new Gitea repository and return its URLs.

        Com `owner`, o repositório nasce na conta daquele usuário (sempre
        privado), criado pela conta de serviço via API de admin. Sem ele, fica
        na conta de serviço — é o caso do admin break-glass.

        Nome ocupado (409) nunca reaproveita o repositório existente, que é de
        outro projeto: tenta `nome-2`, `nome-3`...
        """
        base_name = self.slugify_name(name)
        repo_owner = owner or self.username
        if owner:
            private = True
            endpoint = f"{self.internal_base_url}/api/v1/admin/users/{owner}/repos"
        else:
            endpoint = f"{self.internal_base_url}/api/v1/user/repos"

        repo_name = None
        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(20):
                candidate = base_name if attempt == 0 else f"{base_name}-{attempt + 1}"
                payload = {
                    "name": candidate,
                    "description": description or f"Painkiller project: {name}",
                    "private": private,
                    "auto_init": False,
                }
                res = await client.post(endpoint, json=payload, auth=self._auth())
                if res.status_code == 401:
                    await self.ensure_admin_user()
                    res = await client.post(endpoint, json=payload, auth=self._auth())
                if res.status_code == 201:
                    repo_name = candidate
                    break
                if res.status_code != 409:
                    logger.error(f"Gitea create_repository failed [{res.status_code}]: {res.text}")
                    raise RuntimeError(f"Gitea repository creation failed: {res.status_code} - {res.text}")
        if repo_name is None:
            raise RuntimeError(f"No free Gitea repository name for {name}")

        # Sem credencial na URL: ela iria para o .git/config do repositório, que
        # o agente lê dentro do contêiner. O push autentica pelo GitCliAdapter.
        parsed_internal = urllib.parse.urlparse(self.internal_base_url)
        scheme = parsed_internal.scheme or "http"
        internal_clone_url = f"{scheme}://{parsed_internal.netloc}/{repo_owner}/{repo_name}.git"
        external_web_url = f"{self.external_base_url}/{repo_owner}/{repo_name}"

        return {
            "name": repo_name,
            "clone_url_internal": internal_clone_url,
            "web_url_external": external_web_url,
        }

    def repo_from_url(self, web_url: Optional[str]) -> Optional[tuple[str, str]]:
        """(owner, repo) of a project's `repo_url`, or None when it is not on this Gitea."""
        prefix = self.external_base_url + "/"
        if not web_url or not web_url.startswith(prefix):
            return None
        parts = web_url[len(prefix):].strip("/").split("/")
        if len(parts) != 2 or not all(parts):
            return None
        return parts[0], parts[1]

    # ---- issues ---------------------------------------------------------

    async def _api(self, method: str, path: str, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(timeout=10.0) as client:
            return await client.request(
                method, f"{self.internal_base_url}/api/v1{path}", auth=self._auth(), **kwargs
            )

    async def ensure_labels(self, owner: str, repo: str, specs: list[dict]) -> dict[str, int]:
        """Create the missing labels of `specs` ({name, color, description, exclusive}); name → id."""
        res = await self._api("GET", f"/repos/{owner}/{repo}/labels", params={"limit": 100})
        if res.status_code != 200:
            raise RuntimeError(f"Gitea labels failed: {res.status_code} - {res.text}")
        ids = {label["name"]: label["id"] for label in res.json()}
        for spec in specs:
            if spec["name"] in ids:
                continue
            created = await self._api("POST", f"/repos/{owner}/{repo}/labels", json=spec)
            if created.status_code != 201:
                raise RuntimeError(f"Gitea create label failed: {created.status_code} - {created.text}")
            ids[spec["name"]] = created.json()["id"]
        return ids

    async def create_issue(
        self, owner: str, repo: str, title: str, body: str, label_ids: list[int]
    ) -> dict[str, Any]:
        """Open an issue; returns {number, html_url}."""
        res = await self._api(
            "POST",
            f"/repos/{owner}/{repo}/issues",
            json={"title": title, "body": body, "labels": label_ids},
        )
        if res.status_code != 201:
            raise RuntimeError(f"Gitea create issue failed: {res.status_code} - {res.text}")
        data = res.json()
        return {
            "number": data["number"],
            # O html_url segue o ROOT_URL do Gitea; sem ele, montamos pelo externo.
            "html_url": data.get("html_url") or f"{self.external_base_url}/{owner}/{repo}/issues/{data['number']}",
        }

    async def update_issue(
        self,
        owner: str,
        repo: str,
        number: int,
        *,
        title: Optional[str] = None,
        body: Optional[str] = None,
        closed: Optional[bool] = None,
        label_ids: Optional[list[int]] = None,
    ) -> None:
        """Edit an issue's text/state and replace its labels."""
        fields: dict[str, Any] = {}
        if title is not None:
            fields["title"] = title
        if body is not None:
            fields["body"] = body
        if closed is not None:
            fields["state"] = "closed" if closed else "open"
        if fields:
            res = await self._api("PATCH", f"/repos/{owner}/{repo}/issues/{number}", json=fields)
            if res.status_code != 201 and res.status_code != 200:
                raise RuntimeError(f"Gitea edit issue failed: {res.status_code} - {res.text}")
        if label_ids is not None:
            res = await self._api(
                "PUT", f"/repos/{owner}/{repo}/issues/{number}/labels", json={"labels": label_ids}
            )
            if res.status_code != 200:
                raise RuntimeError(f"Gitea issue labels failed: {res.status_code} - {res.text}")

    async def comment_issue(self, owner: str, repo: str, number: int, body: str) -> None:
        res = await self._api("POST", f"/repos/{owner}/{repo}/issues/{number}/comments", json={"body": body})
        if res.status_code != 201:
            raise RuntimeError(f"Gitea comment failed: {res.status_code} - {res.text}")

    async def archive_repository(self, web_url: str) -> bool:
        """Archive the repository behind a project's `repo_url`; False if it is not ours.

        Arquivar, e não apagar: o repositório some do uso mas continua
        recuperável pelo admin do Gitea.
        """
        located = self.repo_from_url(web_url)
        if located is None:
            return False
        owner, repo = located
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.patch(
                f"{self.internal_base_url}/api/v1/repos/{owner}/{repo}",
                json={"archived": True},
                auth=self._auth(),
            )
            if res.status_code == 404:
                return False
            if res.status_code != 200:
                raise RuntimeError(f"Gitea archive failed: {res.status_code} - {res.text}")
        return True

    def get_branch_url(self, repo_name: str, branch_name: str) -> str:
        """Return web URL to inspect a specific branch in Gitea."""
        slug = self.slugify_name(repo_name)
        return f"{self.external_base_url}/{self.username}/{slug}/src/branch/{branch_name}"

    def get_diff_url(self, repo_name: str, branch_name: str, base_branch: str = "main") -> str:
        """Return web URL to compare/diff a branch against base branch in Gitea."""
        slug = self.slugify_name(repo_name)
        return f"{self.external_base_url}/{self.username}/{slug}/compare/{base_branch}...{branch_name}"

    def get_commit_url(self, repo_name: str, commit_sha: str) -> str:
        """Return web URL to view a specific commit in Gitea."""
        slug = self.slugify_name(repo_name)
        return f"{self.external_base_url}/{self.username}/{slug}/commit/{commit_sha}"
