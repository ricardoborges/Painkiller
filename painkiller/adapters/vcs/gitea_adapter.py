"""Gitea VCS Adapter for managing remote git repositories."""

import asyncio
import logging
import os
import re
import urllib.parse
from typing import Optional, Any
import httpx
import docker

logger = logging.getLogger(__name__)


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
            or os.environ.get("PAINKILLER_GITEA_EXTERNAL_URL", "http://localhost:3300")
        ).rstrip("/")
        self.username = username or os.environ.get("PAINKILLER_GITEA_USER", "painkiller")
        self.password = password or os.environ.get("PAINKILLER_GITEA_PASSWORD", "painkiller_secret_2026")
        self.email = email or os.environ.get("PAINKILLER_GITEA_EMAIL", "bot@painkiller.local")
        self.container_name = container_name or os.environ.get("PAINKILLER_GITEA_CONTAINER_NAME", "painkiller-gitea")
        self._docker_client = docker_client

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

    @staticmethod
    def slugify_name(name: str) -> str:
        """Convert a project name to a valid Gitea repository name."""
        cleaned = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE).strip().lower()
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

    async def create_repository(
        self,
        name: str,
        description: str = "",
        private: bool = False,
    ) -> dict[str, str]:
        """Create a Gitea repository or return existing repository URLs."""
        repo_name = self.slugify_name(name)
        endpoint = f"{self.internal_base_url}/api/v1/user/repos"
        payload = {
            "name": repo_name,
            "description": description or f"Painkiller project: {name}",
            "private": private,
            "auto_init": False,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(endpoint, json=payload, auth=self._auth())
            if res.status_code not in (201, 409):
                # If unauthorized, try ensuring the user once and retry
                if res.status_code == 401:
                    await self.ensure_admin_user()
                    res = await client.post(endpoint, json=payload, auth=self._auth())

            if res.status_code not in (201, 409):
                logger.error(f"Gitea create_repository failed [{res.status_code}]: {res.text}")
                raise RuntimeError(f"Gitea repository creation failed: {res.status_code} - {res.text}")

        # Parse internal host for git clone/push
        parsed_internal = urllib.parse.urlparse(self.internal_base_url)
        netloc = parsed_internal.netloc
        safe_user = urllib.parse.quote(self.username)
        safe_pass = urllib.parse.quote(self.password)
        scheme = parsed_internal.scheme or "http"

        internal_clone_url = f"{scheme}://{safe_user}:{safe_pass}@{netloc}/{self.username}/{repo_name}.git"
        external_web_url = f"{self.external_base_url}/{self.username}/{repo_name}"

        return {
            "name": repo_name,
            "clone_url_internal": internal_clone_url,
            "web_url_external": external_web_url,
        }

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
