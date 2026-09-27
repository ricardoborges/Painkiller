"""Coolify adapter implementing DeploymentPort over the Coolify REST API (v1).

Fluxo: o repositório do projeto vive no Gitea embutido; o Coolify clona a
branch principal como "aplicação pública", constrói (nixpacks ou Dockerfile)
e expõe numa URL. Endpoints usados:

  POST /api/v1/applications/public      cria a aplicação
  GET  /api/v1/applications/{uuid}      fqdn e status da aplicação
  POST /api/v1/deploy?uuid=...          dispara build + deploy
  GET  /api/v1/deployments/{uuid}       status de um deploy
"""

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from painkiller.core.domain.models import DeploymentInfo, DeploymentStatus, Project
from painkiller.core.ports.deployment import DeploymentPort

logger = logging.getLogger(__name__)

VALID_BUILD_PACKS = ("nixpacks", "railpack", "static", "dockerfile", "dockercompose")


def slugify(name: str) -> str:
    """Nome de aplicação aceitável pelo Coolify e utilizável num hostname."""
    cleaned = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE).strip().lower()
    slug = re.sub(r"[-\s_]+", "-", cleaned).strip("-")
    return slug or "app"


class CoolifyAdapter(DeploymentPort):
    """Publishes projects through a self-hosted Coolify instance."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        project_uuid: Optional[str] = None,
        server_uuid: Optional[str] = None,
        environment_name: Optional[str] = None,
        domain_template: Optional[str] = None,
        git_base_url: Optional[str] = None,
        gitea_external_url: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        timeout: float = 30.0,
    ):
        self.base_url = (base_url or os.environ.get("COOLIFY_URL", "")).strip().rstrip("/")
        self.token = (token or os.environ.get("COOLIFY_TOKEN", "")).strip()
        self.project_uuid = (project_uuid or os.environ.get("COOLIFY_PROJECT_UUID", "")).strip()
        self.server_uuid = (server_uuid or os.environ.get("COOLIFY_SERVER_UUID", "")).strip()
        self.environment_name = (
            environment_name or os.environ.get("COOLIFY_ENVIRONMENT_NAME", "") or "production"
        ).strip()
        # Ex.: "https://{slug}.apps.exemplo.com.br". Vazio deixa o Coolify
        # atribuir o domínio padrão do servidor (sslip.io).
        self.domain_template = (domain_template or os.environ.get("COOLIFY_DOMAIN_TEMPLATE", "")).strip()
        # O Coolify pode enxergar o Gitea por outro endereço que o navegador
        # do usuário (rede interna, IP do host). Se definido, substitui o
        # prefixo externo do Gitea na URL de clone.
        self.git_base_url = (git_base_url or os.environ.get("COOLIFY_GIT_BASE_URL", "")).strip().rstrip("/")
        self.gitea_external_url = (
            gitea_external_url or os.environ.get("PAINKILLER_GITEA_EXTERNAL_URL", "http://localhost:3000")
        ).strip().rstrip("/")
        self._transport = transport
        self._timeout = timeout

    # ---- configuração ----------------------------------------------------

    def is_configured(self) -> bool:
        return all((self.base_url, self.token, self.project_uuid, self.server_uuid))

    def missing_settings(self) -> list[str]:
        names = {
            "COOLIFY_URL": self.base_url,
            "COOLIFY_TOKEN": self.token,
            "COOLIFY_PROJECT_UUID": self.project_uuid,
            "COOLIFY_SERVER_UUID": self.server_uuid,
        }
        return [k for k, v in names.items() if not v]

    def _require_configured(self) -> None:
        if not self.is_configured():
            missing = ", ".join(self.missing_settings())
            raise RuntimeError(
                "Publicação não configurada. Defina no .env as variáveis do Coolify: "
                f"{missing}."
            )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{self.base_url}/api/v1",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            },
            timeout=self._timeout,
            transport=self._transport,
        )

    def clone_url_for(self, project: Project) -> str:
        """URL pública de clone que o Coolify usa para buscar o código."""
        if not project.repo_url:
            raise RuntimeError(
                "O projeto não tem repositório remoto (Gitea). Sem ele o Coolify não "
                "consegue buscar o código para publicar."
            )
        url = project.repo_url
        if self.git_base_url and url.startswith(self.gitea_external_url):
            url = self.git_base_url + url[len(self.gitea_external_url):]
        return url if url.endswith(".git") else f"{url}.git"

    # ---- operações -------------------------------------------------------

    async def ensure_application(self, project: Project) -> DeploymentInfo:
        self._require_configured()
        current = project.deployment or DeploymentInfo()
        if current.app_uuid:
            return current

        git_url = self.clone_url_for(project)
        build_pack = current.build_pack if current.build_pack in VALID_BUILD_PACKS else "nixpacks"
        slug = slugify(project.name)
        payload: dict[str, Any] = {
            "project_uuid": self.project_uuid,
            "server_uuid": self.server_uuid,
            "environment_name": self.environment_name,
            "git_repository": git_url,
            "git_branch": project.default_branch,
            "build_pack": build_pack,
            "ports_exposes": str(current.port or 3000),
            "name": f"{slug}-{project.id}",
            "description": f"Painkiller: {project.name}",
            "instant_deploy": False,
        }
        if build_pack == "dockerfile" and current.dockerfile_location:
            payload["dockerfile_location"] = current.dockerfile_location
        if self.domain_template:
            payload["domains"] = self.domain_template.format(slug=slug, id=project.id)

        async with self._client() as client:
            res = await client.post("/applications/public", json=payload)
            self._raise_for_status(res, "criar a aplicação no Coolify")
            app_uuid = (res.json() or {}).get("uuid")
            if not app_uuid:
                raise RuntimeError("O Coolify criou a aplicação mas não devolveu o uuid.")
            url = await self._fetch_fqdn(client, app_uuid)

        return current.model_copy(
            update={
                "provider": "coolify",
                "build_pack": build_pack,
                "app_uuid": app_uuid,
                "url": url,
                "status": DeploymentStatus.CREATED,
                "error": None,
                "updated_at": datetime.now(timezone.utc),
            }
        )

    async def deploy(self, project: Project) -> DeploymentInfo:
        self._require_configured()
        current = project.deployment
        if not current or not current.app_uuid:
            raise RuntimeError("A aplicação ainda não foi criada no Coolify; crie-a antes de publicar.")

        async with self._client() as client:
            params = {"uuid": current.app_uuid, "force": "false"}
            res = await client.post("/deploy", params=params)
            if res.status_code == 405:
                # Versões anteriores do Coolify expunham o disparo como GET.
                res = await client.get("/deploy", params=params)
            self._raise_for_status(res, "disparar o deploy no Coolify")
            body = res.json() or {}
            deployments = body.get("deployments") or []
            deployment_uuid = deployments[0].get("deployment_uuid") if deployments else None
            url = current.url or await self._fetch_fqdn(client, current.app_uuid)

        return current.model_copy(
            update={
                "last_deployment_uuid": deployment_uuid,
                "url": url,
                "status": DeploymentStatus.DEPLOYING,
                "error": None,
                "updated_at": datetime.now(timezone.utc),
            }
        )

    async def refresh_status(self, project: Project) -> DeploymentInfo:
        self._require_configured()
        current = project.deployment
        if not current or not current.app_uuid:
            return current or DeploymentInfo()

        status = current.status
        error = current.error
        url = current.url
        async with self._client() as client:
            if current.last_deployment_uuid and status in (
                DeploymentStatus.DEPLOYING,
                DeploymentStatus.CREATED,
            ):
                res = await client.get(f"/deployments/{current.last_deployment_uuid}")
                if res.status_code == 200:
                    dep_status = str((res.json() or {}).get("status") or "").lower()
                    if dep_status in ("queued", "in_progress"):
                        status = DeploymentStatus.DEPLOYING
                    elif dep_status == "finished":
                        status = DeploymentStatus.LIVE
                        error = None
                    elif dep_status in ("failed", "cancelled-by-user", "cancelled"):
                        status = DeploymentStatus.FAILED
                        error = f"Deploy terminou com status '{dep_status}' no Coolify."
            try:
                url = await self._fetch_fqdn(client, current.app_uuid) or url
            except RuntimeError:
                pass

        return current.model_copy(
            update={"status": status, "error": error, "url": url, "updated_at": datetime.now(timezone.utc)}
        )

    # ---- auxiliares ------------------------------------------------------

    @staticmethod
    async def _fetch_fqdn(client: httpx.AsyncClient, app_uuid: str) -> Optional[str]:
        res = await client.get(f"/applications/{app_uuid}")
        if res.status_code != 200:
            return None
        fqdn = (res.json() or {}).get("fqdn") or ""
        # O Coolify aceita vários domínios separados por vírgula; o primeiro
        # é o que mostramos ao usuário.
        first = fqdn.split(",")[0].strip()
        return first or None

    @staticmethod
    def _raise_for_status(res: httpx.Response, action: str) -> None:
        if res.status_code < 400:
            return
        detail = ""
        try:
            body = res.json()
            detail = body.get("message") or body.get("error") or str(body)
        except Exception:
            detail = res.text[:300]
        if res.status_code == 401:
            raise RuntimeError("O Coolify recusou o token (401). Verifique COOLIFY_TOKEN.")
        raise RuntimeError(f"Falha ao {action} ({res.status_code}): {detail}")
