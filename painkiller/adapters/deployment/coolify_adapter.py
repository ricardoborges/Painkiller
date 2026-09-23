"""Coolify Deployment Adapter using async httpx to orchestrate on-premise environments."""

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Any
import httpx

from painkiller.core.domain.models import (
    Project,
    DeploymentRecord,
    DeploymentStatus,
    EnvironmentType,
)
from painkiller.core.ports.deployment import DeploymentPort

logger = logging.getLogger(__name__)


def generate_ssh_keypair() -> tuple[str, str]:
    """Generate an ed25519 pair: (OpenSSH private key PEM, `ssh-ed25519 ...` public line)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode()
    public_line = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH,
    ).decode()
    return private_pem, public_line


class CoolifyAdapter(DeploymentPort):
    """Integrates with Coolify v4 REST API to provision and deploy test and production environments."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_token: Optional[str] = None,
        server_uuid: Optional[str] = None,
        wildcard_domain: Optional[str] = None,
        gitea_internal_url: Optional[str] = None,
        gitea_external_url: Optional[str] = None,
        vcs: Optional[Any] = None,
    ):
        # GiteaAdapter: com ele, repositórios do nosso Gitea (sempre privados)
        # são clonados por SSH com um deploy key; sem ele, clone público.
        self.vcs = vcs
        self.api_url = (api_url if api_url is not None else os.environ.get("COOLIFY_API_URL", "http://localhost:8000")).rstrip("/")
        self.api_token = os.environ.get("COOLIFY_API_TOKEN", "") if api_token is None else api_token
        self.server_uuid = server_uuid or os.environ.get("COOLIFY_SERVER_UUID", "")
        self.wildcard_domain = (
            wildcard_domain
            or os.environ.get("COOLIFY_WILDCARD_DOMAIN", "127.0.0.1.nip.io")
        ).strip(".")
        self.gitea_internal_url = (
            gitea_internal_url
            or os.environ.get("COOLIFY_GITEA_URL")
            or os.environ.get("PAINKILLER_GITEA_INTERNAL_URL", "http://painkiller-gitea:3000")
        ).rstrip("/")
        self.gitea_external_url = (
            gitea_external_url
            or os.environ.get("PAINKILLER_GITEA_EXTERNAL_URL", "http://localhost:8000/gitea")
        ).rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _resolve_slug(self, project: Project) -> str:
        """Resolve a unique DNS/URL safe identifier for the project."""
        raw = project.id.removeprefix("proj-")
        parts = raw.split("-")
        # If there are at least 3 parts (e.g. user-project-code), use the composite slug
        if len(parts) >= 3:
            clean = "".join(c if c.isalnum() else "-" for c in raw.lower()).strip("-")
            if clean:
                return clean[:45].rstrip("-")
        clean_name = "".join(c if c.isalnum() else "-" for c in project.name.lower()).strip("-")
        return clean_name or "app"

    def _generate_fqdn(self, project: Project, environment: EnvironmentType) -> str:
        slug = self._resolve_slug(project)
        max_label_len = 63 - len(f"-{environment.value}")
        clean_label = slug[:max_label_len].rstrip("-")
        return f"http://{clean_label}-{environment.value}.{self.wildcard_domain}"

    def _resolve_repo_url(self, project: Project) -> str:
        """Resolve the Git repository URL that Coolify can reach."""
        # O repo_url guardado é o endereço externo do Gitea (ex.: o proxy
        # http://localhost:8000/gitea/...), que o Coolify recusa por apontar
        # para localhost e que, de todo modo, não resolve dentro do container
        # de build. Reescreve o prefixo para o Gitea na rede do docker.
        if not project.repo_url:
            slug = self._resolve_slug(project)
            return f"{self.gitea_internal_url}/painkiller/{slug}.git"

        url = project.repo_url
        external_prefixes = [
            self.gitea_external_url,
            # Endereços de versões antigas, com o Gitea exposto direto no host.
            "http://localhost:3300",
            "http://127.0.0.1:3300",
        ]
        for prefix in external_prefixes:
            if prefix and url.startswith(prefix + "/"):
                url = self.gitea_internal_url + url[len(prefix):]
                break
        if not url.endswith(".git"):
            url += ".git"
        return url

    async def _ensure_deploy_key(
        self, client: httpx.AsyncClient, owner: str, repo: str, slug: str
    ) -> str:
        """Return the uuid of the Coolify private key that clones this repo.

        Um par por projeto, reaproveitado por teste e produção. A pública vai
        como deploy key só-leitura no Gitea; a privada fica guardada só no
        Coolify, então o Painkiller não precisa persistir nada.
        """
        key_name = f"painkiller-{slug}"
        resp = await client.get(f"{self.api_url}/api/v1/security/keys", headers=self._headers())
        if resp.is_success:
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            for k in items:
                if k.get("name") == key_name and k.get("uuid"):
                    return k["uuid"]

        private_pem, public_openssh = generate_ssh_keypair()
        await self.vcs.add_deploy_key(owner, repo, key_name, public_openssh)
        create_resp = await client.post(
            f"{self.api_url}/api/v1/security/keys",
            headers=self._headers(),
            json={
                "name": key_name,
                "description": f"Deploy key do Painkiller para {owner}/{repo}",
                "private_key": private_pem,
            },
        )
        if not create_resp.is_success:
            raise RuntimeError(f"Falha ao registrar chave SSH no Coolify: {create_resp.text}")
        return create_resp.json().get("uuid", "")

    async def _get_or_create_project(self, client: httpx.AsyncClient, project: Project) -> str:
        """Get or create the Coolify project uuid matching Painkiller project."""
        if project.coolify_project_uuid:
            return project.coolify_project_uuid

        # List projects in Coolify
        resp = await client.get(f"{self.api_url}/api/v1/projects", headers=self._headers())
        if resp.is_success:
            data = resp.json()
            items = data if isinstance(data, list) else data.get("projects", [])
            for p in items:
                name = p.get("name", "")
                if project.id in name or name == f"painkiller-{project.name}":
                    return p.get("uuid")

        # Create new project in Coolify
        proj_name = f"painkiller-{project.id}" if len(project.id.split("-")) >= 3 else f"painkiller-{project.name}-{project.id[:6]}"
        create_resp = await client.post(
            f"{self.api_url}/api/v1/projects",
            headers=self._headers(),
            json={
                "name": proj_name,
                "description": project.description or f"Painkiller project {project.name}",
            },
        )
        if create_resp.is_success:
            created = create_resp.json()
            return created.get("uuid", "")
        return ""

    async def _ensure_environment(self, client: httpx.AsyncClient, project_uuid: str, env_name: str) -> None:
        """Ensure the specified environment (e.g. test, production) exists in Coolify project."""
        if not project_uuid:
            return
        resp = await client.get(f"{self.api_url}/api/v1/projects/{project_uuid}/environments", headers=self._headers())
        if resp.is_success:
            envs = resp.json()
            items = envs if isinstance(envs, list) else []
            for e in items:
                if e.get("name") == env_name:
                    return
        await client.post(
            f"{self.api_url}/api/v1/projects/{project_uuid}/environments",
            headers=self._headers(),
            json={"name": env_name},
        )

    async def _get_server_uuid(self, client: httpx.AsyncClient) -> str:
        if self.server_uuid:
            return self.server_uuid
        resp = await client.get(f"{self.api_url}/api/v1/servers", headers=self._headers())
        if resp.is_success:
            servers = resp.json()
            if isinstance(servers, list) and servers:
                return servers[0].get("uuid", "0")
        return "0"

    def _detect_build_pack(self, project: Project) -> tuple[str, bool]:
        """Detect the build pack and whether it's static."""
        repo_path = project.repo_path
        if repo_path and os.path.isdir(repo_path):
            if os.path.exists(os.path.join(repo_path, "Dockerfile")):
                return "dockerfile", False
            if os.path.exists(os.path.join(repo_path, "docker-compose.yml")) or os.path.exists(os.path.join(repo_path, "docker-compose.yaml")):
                return "dockercompose", False
            if os.path.exists(os.path.join(repo_path, "package.json")):
                return "nixpacks", False
            if os.path.exists(os.path.join(repo_path, "requirements.txt")) or os.path.exists(os.path.join(repo_path, "pyproject.toml")):
                return "nixpacks", False
            if os.path.exists(os.path.join(repo_path, "index.html")):
                return "static", True
        return "nixpacks", False

    async def deploy_environment(
        self,
        project: Project,
        environment: EnvironmentType,
        branch: str,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> DeploymentRecord:
        deployment_id = f"dep-{uuid.uuid4().hex[:10]}"
        fqdn = self._generate_fqdn(project, environment)
        now = datetime.now(timezone.utc)

        # Se o token não estiver configurado, registra como mock / dev local com URL prevista
        if not self.api_token:
            logger.warning("COOLIFY_API_TOKEN não configurado. Simulando registro de deploy.")
            return DeploymentRecord(
                id=deployment_id,
                project_id=project.id,
                task_id=task_id,
                session_id=session_id,
                environment=environment,
                branch=branch,
                status=DeploymentStatus.HEALTHY,
                coolify_app_uuid=f"mock-app-{project.id}-{environment.value}",
                coolify_deployment_uuid=f"mock-dep-{deployment_id}",
                url=fqdn,
                logs=f"Ambiente simulado (COOLIFY_API_TOKEN ausente). Apontando para {fqdn}",
                created_at=now,
                updated_at=now,
            )

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                # 1. Obter ou criar Projeto no Coolify e garantir o ambiente
                coolify_proj_uuid = await self._get_or_create_project(client, project)
                await self._ensure_environment(client, coolify_proj_uuid, environment.value)
                server_uuid = await self._get_server_uuid(client)
                repo_url = self._resolve_repo_url(project)

                # 2. Localizar se aplicação já existe no Coolify
                slug = self._resolve_slug(project)
                app_name = f"{slug}-{environment.value}"
                app_uuid: Optional[str] = None

                apps_resp = await client.get(f"{self.api_url}/api/v1/applications", headers=self._headers())
                if apps_resp.is_success:
                    apps_data = apps_resp.json()
                    apps_list = apps_data if isinstance(apps_data, list) else apps_data.get("applications", [])
                    for a in apps_list:
                        if a.get("name") == app_name or a.get("fqdn") == fqdn:
                            app_uuid = a.get("uuid")
                            break

                build_pack, is_static = self._detect_build_pack(project)

                # 3. Criar aplicação se não existir
                if not app_uuid:
                    payload = {
                        "project_uuid": coolify_proj_uuid,
                        "server_uuid": server_uuid,
                        "environment_name": environment.value,
                        "name": app_name,
                        "git_repository": repo_url,
                        "git_branch": branch,
                        "build_pack": build_pack,
                        "is_static": is_static,
                        "ports_exposes": "80",
                        "domains": fqdn,
                    }
                    endpoint = "public"
                    # Repositório do nosso Gitea: privado (FORCE_PRIVATE), então
                    # o clone anônimo falharia. Vai por SSH com deploy key.
                    located = self.vcs.repo_from_url(project.repo_url) if self.vcs else None
                    if located:
                        owner, repo = located
                        payload["private_key_uuid"] = await self._ensure_deploy_key(
                            client, owner, repo, slug
                        )
                        payload["git_repository"] = self.vcs.ssh_clone_url(owner, repo)
                        endpoint = "private-deploy-key"
                    create_app_resp = await client.post(
                        f"{self.api_url}/api/v1/applications/{endpoint}",
                        headers=self._headers(),
                        json=payload,
                    )
                    if create_app_resp.is_success:
                        app_data = create_app_resp.json()
                        app_uuid = app_data.get("uuid")
                    else:
                        error_text = create_app_resp.text
                        logger.error(f"Erro ao criar aplicação no Coolify: {error_text}")
                        return DeploymentRecord(
                            id=deployment_id,
                            project_id=project.id,
                            task_id=task_id,
                            session_id=session_id,
                            environment=environment,
                            branch=branch,
                            status=DeploymentStatus.FAILED,
                            url=fqdn,
                            logs=f"Falha ao registrar aplicação no Coolify: {error_text}",
                            created_at=now,
                            updated_at=now,
                        )
                else:
                    # Atualiza a branch e configurações caso a aplicação já existisse.
                    # Uma recusa aqui deixaria o deploy rodar na branch anterior
                    # sem aviso, então vira falha explícita.
                    patch_resp = await client.patch(
                        f"{self.api_url}/api/v1/applications/{app_uuid}",
                        headers=self._headers(),
                        json={
                            "git_branch": branch,
                            "domains": fqdn,
                            "build_pack": build_pack,
                            "is_static": is_static,
                        },
                    )
                    if not patch_resp.is_success:
                        error_text = patch_resp.text
                        logger.error(f"Erro ao atualizar aplicação no Coolify: {error_text}")
                        return DeploymentRecord(
                            id=deployment_id,
                            project_id=project.id,
                            task_id=task_id,
                            session_id=session_id,
                            environment=environment,
                            branch=branch,
                            status=DeploymentStatus.FAILED,
                            coolify_app_uuid=app_uuid,
                            url=fqdn,
                            logs=f"Falha ao apontar a aplicação do Coolify para a branch {branch}: {error_text}",
                            created_at=now,
                            updated_at=now,
                        )

                # 4. Disparar Deploy no Coolify
                deploy_resp = await client.post(
                    f"{self.api_url}/api/v1/deploy?uuid={app_uuid}&force=false",
                    headers=self._headers(),
                )
                coolify_dep_uuid: Optional[str] = None
                status = DeploymentStatus.BUILDING

                if deploy_resp.is_success:
                    deploy_data = deploy_resp.json()
                    coolify_dep_uuid = (
                        deploy_data.get("deployment_uuid")
                        or (deploy_data.get("deployments", [{}])[0].get("deployment_uuid") if isinstance(deploy_data.get("deployments"), list) else None)
                    )
                else:
                    logger.warning(f"Resposta de deploy do Coolify: {deploy_resp.status_code} {deploy_resp.text}")

                return DeploymentRecord(
                    id=deployment_id,
                    project_id=project.id,
                    task_id=task_id,
                    session_id=session_id,
                    environment=environment,
                    branch=branch,
                    status=status,
                    coolify_app_uuid=app_uuid,
                    coolify_deployment_uuid=coolify_dep_uuid,
                    url=fqdn,
                    logs="Deploy disparado com sucesso no Coolify.",
                    created_at=now,
                    updated_at=now,
                )

            except Exception as e:
                logger.exception(f"Exceção ao comunicar com Coolify: {e}")
                return DeploymentRecord(
                    id=deployment_id,
                    project_id=project.id,
                    task_id=task_id,
                    session_id=session_id,
                    environment=environment,
                    branch=branch,
                    status=DeploymentStatus.FAILED,
                    url=fqdn,
                    logs=f"Erro ao provisionar no Coolify: {str(e)}",
                    created_at=now,
                    updated_at=now,
                )

    async def get_deployment_status(self, record: DeploymentRecord) -> DeploymentRecord:
        if not self.api_token or not record.coolify_deployment_uuid:
            return record

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(
                    f"{self.api_url}/api/v1/deployments/{record.coolify_deployment_uuid}",
                    headers=self._headers(),
                )
                if resp.is_success:
                    data = resp.json()
                    c_status = str(data.get("status", "")).lower()
                    if c_status in ("finished", "success", "healthy"):
                        record.status = DeploymentStatus.HEALTHY
                    elif c_status in ("failed", "error"):
                        record.status = DeploymentStatus.FAILED
                    elif c_status in ("in_progress", "queued", "building"):
                        record.status = DeploymentStatus.BUILDING
                    elif c_status in ("killed", "stopped", "cancelled"):
                        record.status = DeploymentStatus.STOPPED

                    logs = data.get("logs")
                    if logs:
                        record.logs = logs
                    record.updated_at = datetime.now(timezone.utc)
            except Exception as e:
                logger.debug(f"Falha ao consultar status de deploy no Coolify: {e}")

        return record

    async def get_deployment_logs(self, record: DeploymentRecord) -> str:
        if not self.api_token or not record.coolify_deployment_uuid:
            return record.logs or "Sem logs disponíveis."

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(
                    f"{self.api_url}/api/v1/deployments/{record.coolify_deployment_uuid}",
                    headers=self._headers(),
                )
                if resp.is_success:
                    data = resp.json()
                    return str(data.get("logs") or record.logs or "Logs vazios.")
            except Exception as e:
                return f"Erro ao obter logs: {e}"
        return record.logs or ""
