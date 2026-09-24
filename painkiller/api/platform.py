"""Platform configuration: what the first access and the setup wizard save.

A fonte única é o banco (SQLite): nada disto é lido do `.env`. Um campo vazio
cai no padrão do código, ou no valor detectado (pasta no host, URL pela qual o
admin abriu a plataforma). Salvar reaplica tudo aos adapters na hora, sem
restart.
"""

import asyncio
import logging
import os
import urllib.parse
from typing import Any, Optional

from painkiller.adapters.sandbox.paths import container_root, detect_host_root, set_host_root
from painkiller.api import security
from painkiller.core.domain.models import SETUP_STEPS, PlatformSettings, SetupStepStatus
from painkiller.core.ports.platform_settings import PlatformSettingsPort

logger = logging.getLogger(__name__)

DEFAULT_PUBLIC_URL = "http://localhost:8000"
DEFAULT_COOLIFY_PORT = "8008"

#: Comprimento mínimo da senha do administrador.
MIN_ADMIN_PASSWORD = 12


class AdminAccountError(ValueError):
    """Invalid administrator data; the message is pt-BR, fit for the UI."""


def _host_of(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or "localhost"


def suggest_wildcard_domain(public_url: str) -> str:
    """nip.io resolves `<ip>.nip.io` to the IP itself, so no DNS is needed locally."""
    host = _host_of(public_url)
    if host in ("localhost", "0.0.0.0"):
        return "127.0.0.1.nip.io"
    if host.replace(".", "").isdigit():
        return f"{host}.nip.io"
    return host


def validate_admin(username: str, password: str) -> tuple[str, str]:
    username = (username or "").strip()
    if not username or len(username) > 64 or any(c.isspace() for c in username):
        raise AdminAccountError("O usuário precisa ter de 1 a 64 caracteres, sem espaços.")
    if len(password or "") < MIN_ADMIN_PASSWORD:
        raise AdminAccountError(f"A senha precisa ter pelo menos {MIN_ADMIN_PASSWORD} caracteres.")
    return username, password


class PlatformConfig:
    """Loads, resolves and applies the platform settings."""

    def __init__(
        self,
        store: PlatformSettingsPort,
        state: Any = None,
        docker_client_factory: Optional[Any] = None,
    ):
        self.store = store
        # app.state, lido a cada apply: os testes trocam google_oauth e deployment
        # depois de create_app.
        self.state = state
        self.docker_client_factory = docker_client_factory
        self.settings = PlatformSettings()
        self.detected_host_root: Optional[str] = None
        # URL pela qual o admin abriu o wizard: palpite da URL pública até ele salvar uma.
        self.observed_url: Optional[str] = None
        # Serializa o primeiro acesso: duas abas não criam dois administradores.
        self._admin_lock = asyncio.Lock()

    def docker_client(self):
        if self.docker_client_factory is not None:
            return self.docker_client_factory()
        import docker

        return docker.from_env()

    async def load(self) -> PlatformSettings:
        """Read the stored settings, install the signing key, detect the host root and apply."""
        security.set_auth_secret(await self.store.get_secret_key())
        self.settings = await self.store.get_platform_settings()
        if container_root():
            try:
                client = self.docker_client()
                self.detected_host_root = await asyncio.get_running_loop().run_in_executor(
                    None, detect_host_root, client
                )
            except Exception as e:
                logger.warning(f"Could not detect the host path of the storage folder: {e}")
        self.apply()
        return self.settings

    async def save(self, settings: PlatformSettings) -> PlatformSettings:
        self.settings = await self.store.save_platform_settings(settings)
        self.apply()
        return self.settings

    async def mark(self, step: str, status: SetupStepStatus) -> PlatformSettings:
        settings = self.settings.model_copy(deep=True)
        settings.steps[step] = status
        return await self.save(settings)

    # ---- administrador ---------------------------------------------------

    @property
    def needs_first_access(self) -> bool:
        return not (self.settings.admin_username and self.settings.admin_password_hash)

    async def create_admin(self, username: str, password: str) -> None:
        """First access: create the administrator. Refused once one exists."""
        username, password = validate_admin(username, password)
        async with self._admin_lock:
            # Relê do banco: outro processo pode ter concluído o primeiro acesso.
            self.settings = await self.store.get_platform_settings()
            if not self.needs_first_access:
                raise AdminAccountError("O primeiro acesso já foi feito. Entre com o administrador.")
            settings = self.settings.model_copy(deep=True)
            settings.admin_username = username
            settings.admin_password_hash = security.hash_password(password)
            await self.save(settings)

    async def update_admin(self, current_password: str, username: str, new_password: str = "") -> None:
        """Change the administrator's username and/or password (current password required)."""
        account = security.admin_account()
        if account is None or not security.verify_password(current_password or "", account[1]):
            raise AdminAccountError("A senha atual não confere.")
        settings = self.settings.model_copy(deep=True)
        if new_password:
            username, new_password = validate_admin(username, new_password)
            settings.admin_password_hash = security.hash_password(new_password)
        else:
            username, _ = validate_admin(username, "x" * MIN_ADMIN_PASSWORD)
        settings.admin_username = username
        await self.save(settings)

    # ---- valores efetivos ------------------------------------------------

    def observe(self, url: str) -> None:
        """Remember the URL the admin is using, so every derived link agrees with it."""
        url = url.rstrip("/")
        if url and url != self.observed_url:
            self.observed_url = url
            self.apply()

    def public_url(self) -> str:
        return (self.settings.public_url or self.observed_url or DEFAULT_PUBLIC_URL).rstrip("/")

    def host_root(self) -> tuple[Optional[str], Optional[str]]:
        """(value, source), source being "settings", "detected" or None."""
        if self.settings.host_root:
            return self.settings.host_root, "settings"
        if self.detected_host_root:
            return self.detected_host_root, "detected"
        return None, None

    def google_values(self) -> dict[str, str]:
        s = self.settings
        return {
            "client_id": s.google_client_id or "",
            "client_secret": s.google_client_secret or "",
            "allowed_domains": s.google_allowed_domains or "",
        }

    def google_redirect_uris(self) -> dict[str, str]:
        # A URL externa do Gitea é infraestrutura do compose, não configuração do admin.
        gitea = (os.environ.get("PAINKILLER_GITEA_EXTERNAL_URL") or f"{self.public_url()}/gitea").rstrip("/")
        return {
            "painkiller": f"{self.public_url()}/api/auth/google/callback",
            "gitea": f"{gitea}/user/oauth2/google/callback",
        }

    def coolify_values(self) -> dict[str, str]:
        s = self.settings
        return {
            "api_token": s.coolify_api_token or "",
            "server_uuid": s.coolify_server_uuid or "",
            "wildcard_domain": s.coolify_wildcard_domain or suggest_wildcard_domain(self.public_url()),
        }

    def coolify_dashboard_url(self) -> str:
        """Where the admin's browser reaches Coolify: same host as Painkiller, Coolify's port."""
        if self.settings.coolify_dashboard_url:
            return self.settings.coolify_dashboard_url.rstrip("/")
        parts = urllib.parse.urlsplit(self.public_url())
        # A porta publicada é infraestrutura do compose.
        port = os.environ.get("COOLIFY_PORT") or DEFAULT_COOLIFY_PORT
        return f"{parts.scheme or 'http'}://{parts.hostname or 'localhost'}:{port}"

    def step_status(self, step: str) -> SetupStepStatus:
        return self.settings.steps.get(step, SetupStepStatus.PENDING)

    def steps(self) -> dict[str, str]:
        return {step: self.step_status(step).value for step in SETUP_STEPS}

    # ---- aplicação -------------------------------------------------------

    def apply(self) -> None:
        security.set_admin_account(self.settings.admin_username, self.settings.admin_password_hash)
        set_host_root(self.host_root()[0])

        google_client = getattr(self.state, "google_oauth", None)
        if google_client is not None and hasattr(google_client, "configure"):
            google = self.google_values()
            google_client.configure(
                client_id=google["client_id"],
                client_secret=google["client_secret"],
                redirect_uri=self.google_redirect_uris()["painkiller"],
                allowed_domains=google["allowed_domains"],
            )

        deployment = getattr(self.state, "deployment", None)
        if deployment is not None and hasattr(deployment, "configure"):
            coolify = self.coolify_values()
            deployment.configure(
                api_token=coolify["api_token"],
                server_uuid=coolify["server_uuid"],
                wildcard_domain=coolify["wildcard_domain"],
            )
