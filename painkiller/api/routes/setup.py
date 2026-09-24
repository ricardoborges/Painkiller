"""Setup wizard routes: first-run configuration done by the admin in the UI."""

import asyncio
import logging
import os
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from painkiller.adapters.deployment.coolify_bootstrap import (
    CoolifyBootstrapError,
    generate_password,
)
from painkiller.adapters.sandbox.paths import container_root, daemon_path
from painkiller.api.platform import AdminAccountError, PlatformConfig, suggest_wildcard_domain
from painkiller.api.routes.auth import admin_session
from painkiller.api.security import admin_account, require_admin
from painkiller.core.domain.models import SETUP_STEPS, SetupStepStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setup", tags=["setup"], dependencies=[Depends(require_admin)])

#: Imagens dos harnesses, pelo nome que os adapters instanciam.
HARNESS_IMAGES = (
    ("Antigravity (agy)", "PAINKILLER_AGENT_IMAGE", "painkiller-agent:latest", "PAINKILLER_WORKER_IMAGE", "painkiller-worker:latest"),
    ("DeepSeek (dsh)", "PAINKILLER_AGENT_DEEPSEEK_IMAGE", "painkiller-agent-deepseek:latest", "PAINKILLER_WORKER_DEEPSEEK_IMAGE", "painkiller-worker-deepseek:latest"),
    ("Maki", "PAINKILLER_AGENT_MAKI_IMAGE", "painkiller-agent-maki:latest", "PAINKILLER_WORKER_MAKI_IMAGE", "painkiller-worker-maki:latest"),
    ("Unreal Agent", "PAINKILLER_AGENT_UNREAL_IMAGE", "painkiller-agent-unreal:latest", "PAINKILLER_WORKER_UNREAL_IMAGE", "painkiller-worker-unreal:latest"),
)

#: Arquivo-sentinela que o teste de montagem grava e o contêiner de prova lê.
PROBE_FILE = ".painkiller-mount-probe"

#: E-mail da conta root criada no Coolify quando o admin não informa outro.
DEFAULT_COOLIFY_EMAIL = "admin@painkiller.local"


def _platform(request: Request) -> PlatformConfig:
    return request.app.state.platform


def _mask(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}***{value[-4:]}"


def _storage_dir() -> str:
    return container_root() or os.environ.get("PAINKILLER_STORAGE_DIR") or os.path.join(os.getcwd(), "storage")


def _harness_images(client) -> list[dict]:
    """Which harness images exist locally; missing ones need `compose --profile build build`."""
    rows = []
    for label, agent_env, agent_default, worker_env, worker_default in HARNESS_IMAGES:
        names = [os.environ.get(agent_env) or agent_default, os.environ.get(worker_env) or worker_default]
        present = []
        for name in names:
            try:
                client.images.get(name)
                present.append(True)
            except Exception:
                present.append(False)
        rows.append({"harness": label, "images": names, "present": all(present)})
    return rows


async def _environment(request: Request, platform: PlatformConfig) -> dict:
    host_root, host_root_source = platform.host_root()
    docker_ok = False
    images: list[dict] = []
    try:
        client = platform.docker_client()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, client.ping)
        docker_ok = True
        images = await loop.run_in_executor(None, _harness_images, client)
    except Exception as e:
        logger.debug(f"Docker not reachable for the setup check: {e}")
    return {
        "public_url": platform.public_url(),
        "public_url_saved": bool(platform.settings.public_url),
        "session_ttl_hours": platform.settings.session_ttl_hours or 12,
        "in_container": bool(container_root()),
        "host_root": host_root,
        "host_root_source": host_root_source,
        "detected_host_root": platform.detected_host_root,
        "docker_ok": docker_ok,
        "images": images,
    }


def _google(platform: PlatformConfig) -> dict:
    values = platform.google_values()
    return {
        "client_id": values["client_id"] or "",
        "has_secret": bool(values["client_secret"]),
        "masked_secret": _mask(values["client_secret"]),
        "allowed_domains": values["allowed_domains"] or "",
        "redirect_uris": platform.google_redirect_uris(),
        "enabled": bool(values["client_id"] and values["client_secret"]),
    }


def _coolify(platform: PlatformConfig) -> dict:
    values = platform.coolify_values()
    s = platform.settings
    return {
        "dashboard_url": platform.coolify_dashboard_url(),
        "has_token": bool(values["api_token"]),
        "masked_token": _mask(values["api_token"]),
        "server_uuid": values["server_uuid"] or "",
        "wildcard_domain": values["wildcard_domain"],
        "suggested_wildcard_domain": suggest_wildcard_domain(platform.public_url()),
        "root_email": s.coolify_root_email,
        "has_root_password": bool(s.coolify_root_password),
    }


async def _state(request: Request) -> dict:
    platform = _platform(request)
    platform.observe(str(request.base_url))
    account = admin_account()
    return {
        "completed": platform.settings.completed,
        "admin_username": account[0] if account else None,
        "steps": platform.steps(),
        "environment": await _environment(request, platform),
        "google": _google(platform),
        "coolify": _coolify(platform),
    }


@router.get("")
async def get_setup(request: Request):
    return await _state(request)


# ---- conta do administrador ------------------------------------------------


class AdminAccountRequest(BaseModel):
    current_password: str
    username: str
    # Vazio mantém a senha atual.
    new_password: str = ""


@router.put("/admin")
async def update_admin_account(body: AdminAccountRequest, request: Request, response: Response):
    """Change the administrator's username or password; returns a fresh session token."""
    try:
        await _platform(request).update_admin(body.current_password, body.username, body.new_password)
    except AdminAccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # A senha nova invalida o token atual: devolve outro para a sessão seguir.
    return admin_session(response)


# ---- 1. Ambiente -----------------------------------------------------------


class EnvironmentRequest(BaseModel):
    public_url: Optional[str] = None
    # Vazio = volta à detecção automática.
    host_root: Optional[str] = None
    session_ttl_hours: Optional[int] = None


@router.put("/environment")
async def save_environment(body: EnvironmentRequest, request: Request):
    platform = _platform(request)
    settings = platform.settings.model_copy(deep=True)
    public_url = (body.public_url or "").strip().rstrip("/")
    if public_url and not public_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="A URL pública precisa começar com http:// ou https://.")
    if body.session_ttl_hours is not None and not 1 <= body.session_ttl_hours <= 24 * 30:
        raise HTTPException(status_code=400, detail="A validade da sessão vai de 1 hora a 30 dias (720 h).")
    url_changed = (public_url or None) != settings.public_url
    settings.public_url = public_url or None
    settings.host_root = (body.host_root or "").strip() or None
    if body.session_ttl_hours is not None:
        settings.session_ttl_hours = body.session_ttl_hours
    settings.steps["environment"] = SetupStepStatus.DONE
    await platform.save(settings)
    if url_changed:
        # O Gitea monta links e o retorno do login único com o próprio ROOT_URL.
        asyncio.create_task(platform.sync_gitea_root_url())
    return await _state(request)


def _probe_mount(client, image: str, storage: str, token: str) -> tuple[bool, str]:
    source = daemon_path(storage)
    output = client.containers.run(
        image,
        command=["cat", f"/probe/{PROBE_FILE}"],
        entrypoint=[],
        volumes={source: {"bind": "/probe", "mode": "ro"}},
        remove=True,
        stdout=True,
        stderr=True,
    )
    text = (output or b"").decode("utf-8", errors="replace").strip()
    return text == token, source


@router.post("/environment/test")
async def test_environment(request: Request):
    """Mount the storage folder into a throwaway container, as dispatch will, and read a sentinel."""
    platform = _platform(request)
    storage = _storage_dir()
    token = secrets.token_hex(8)
    probe = os.path.join(storage, PROBE_FILE)
    try:
        os.makedirs(storage, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as f:
            f.write(token)
    except OSError as e:
        return {"ok": False, "detail": f"Não foi possível gravar em {storage}: {e}"}

    loop = asyncio.get_running_loop()
    try:
        client = platform.docker_client()
        images = await loop.run_in_executor(None, _harness_images, client)
        image = next((row["images"][1] for row in images if row["present"]), None)
        if image is None:
            return {
                "ok": False,
                "detail": "Nenhuma imagem de harness construída. Rode `docker compose --profile build build`.",
            }
        ok, source = await loop.run_in_executor(None, _probe_mount, client, image, storage, token)
    except Exception as e:
        return {"ok": False, "detail": f"O contêiner de teste não conseguiu montar a pasta: {e}"}
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass
    if ok:
        return {"ok": True, "detail": f"Os agentes enxergam {source} como /workspace."}
    return {
        "ok": False,
        "detail": f"O contêiner montou {source}, mas a pasta não é a mesma. Confira o caminho no host.",
    }


# ---- 2. Google ---------------------------------------------------------------


class GoogleRequest(BaseModel):
    client_id: str = ""
    # Vazio mantém o secret salvo.
    client_secret: Optional[str] = None
    allowed_domains: str = ""


@router.put("/google")
async def save_google(body: GoogleRequest, request: Request):
    platform = _platform(request)
    settings = platform.settings.model_copy(deep=True)
    client_id = body.client_id.strip()
    secret = (body.client_secret or "").strip()
    if client_id and not client_id.endswith(".apps.googleusercontent.com"):
        raise HTTPException(
            status_code=400,
            detail="O Client ID do Google termina em .apps.googleusercontent.com. Confira o valor copiado.",
        )
    if client_id and not (secret or platform.google_values()["client_secret"]):
        raise HTTPException(status_code=400, detail="Informe também o Client secret.")
    settings.google_client_id = client_id or None
    if secret:
        settings.google_client_secret = secret
    if not client_id:
        settings.google_client_secret = None
    settings.google_allowed_domains = body.allowed_domains.strip()
    settings.steps["google"] = SetupStepStatus.DONE if client_id else SetupStepStatus.SKIPPED
    await platform.save(settings)
    return await _state(request)


# ---- 3. Coolify --------------------------------------------------------------


class CoolifyRequest(BaseModel):
    # Vazio mantém o token salvo.
    api_token: Optional[str] = None
    server_uuid: Optional[str] = None
    wildcard_domain: Optional[str] = None
    dashboard_url: Optional[str] = None


async def _check_coolify(request: Request, token: Optional[str] = None) -> dict:
    deployment = request.app.state.deployment
    if not hasattr(deployment, "check"):
        return {"reachable": False, "token_ok": False, "version": None, "servers": [], "error": "Sem adapter Coolify."}
    return await deployment.check(token)


async def _adopt_single_server(platform: PlatformConfig, check: dict) -> None:
    """With exactly one server there is nothing to choose: save its uuid."""
    servers = check.get("servers") or []
    if check.get("token_ok") and len(servers) == 1 and not platform.settings.coolify_server_uuid:
        settings = platform.settings.model_copy(deep=True)
        settings.coolify_server_uuid = servers[0]["uuid"]
        await platform.save(settings)


@router.get("/coolify/status")
async def coolify_status(request: Request):
    """What is left to do in Coolify: container, root account, API access, token."""
    platform = _platform(request)
    container: dict = {"reachable": False, "root_user": False, "root_email": None, "api_enabled": False, "error": None}
    try:
        container.update(await request.app.state.coolify_bootstrap.inspect())
        container["reachable"] = True
    except CoolifyBootstrapError as e:
        container["error"] = str(e)
    except Exception as e:
        container["error"] = f"Não foi possível inspecionar o Coolify: {e}"
    check = await _check_coolify(request)
    await _adopt_single_server(platform, check)
    return {"container": container, "api": check, "coolify": _coolify(platform)}


@router.put("/coolify")
async def save_coolify(body: CoolifyRequest, request: Request):
    platform = _platform(request)
    token = (body.api_token or "").strip()
    check = await _check_coolify(request, token or None)
    if token and not check.get("token_ok"):
        raise HTTPException(status_code=400, detail=check.get("error") or "O Coolify não aceitou o token.")
    settings = platform.settings.model_copy(deep=True)
    if token:
        settings.coolify_api_token = token
    if body.server_uuid is not None:
        settings.coolify_server_uuid = body.server_uuid.strip() or None
    if body.wildcard_domain is not None:
        settings.coolify_wildcard_domain = body.wildcard_domain.strip().strip(".") or None
    if body.dashboard_url is not None:
        settings.coolify_dashboard_url = body.dashboard_url.strip().rstrip("/") or None
    if platform.coolify_values()["api_token"] or token:
        settings.steps["coolify"] = SetupStepStatus.DONE
    await platform.save(settings)
    await _adopt_single_server(platform, check)
    return await _state(request)


class CoolifyBootstrapRequest(BaseModel):
    email: Optional[str] = None


@router.post("/coolify/bootstrap")
async def coolify_bootstrap(body: CoolifyBootstrapRequest, request: Request):
    """Create Coolify's root account if missing, enable its API and save a fresh token."""
    platform = _platform(request)
    email = (body.email or "").strip() or DEFAULT_COOLIFY_EMAIL
    password = generate_password()
    try:
        result = await request.app.state.coolify_bootstrap.provision(email, password)
    except CoolifyBootstrapError as e:
        raise HTTPException(status_code=502, detail=str(e))

    settings = platform.settings.model_copy(deep=True)
    settings.coolify_api_token = result["token"]
    if result.get("created_user"):
        settings.coolify_root_email = result.get("email") or email
        settings.coolify_root_password = password
    settings.steps["coolify"] = SetupStepStatus.DONE
    await platform.save(settings)

    check = await _check_coolify(request)
    await _adopt_single_server(platform, check)
    return {
        "created_user": bool(result.get("created_user")),
        "email": result.get("email") or email,
        # Só existe quando a conta foi criada agora; uma conta anterior mantém a senha dela.
        "password": password if result.get("created_user") else None,
        "api": check,
        "state": await _state(request),
    }


@router.get("/coolify/credentials")
async def coolify_credentials(request: Request):
    """The Coolify root account the automation created, for the admin to sign in to Coolify."""
    s = _platform(request).settings
    if not s.coolify_root_email:
        raise HTTPException(status_code=404, detail="Nenhuma conta do Coolify foi criada pelo Painkiller.")
    return {"email": s.coolify_root_email, "password": s.coolify_root_password}


# ---- etapas ------------------------------------------------------------------


@router.post("/steps/{step}/skip")
async def skip_step(step: str, request: Request):
    if step not in SETUP_STEPS or step == "environment":
        raise HTTPException(status_code=400, detail="Esta etapa não pode ser pulada.")
    await _platform(request).mark(step, SetupStepStatus.SKIPPED)
    return await _state(request)


@router.post("/complete")
async def complete_setup(request: Request):
    platform = _platform(request)
    settings = platform.settings.model_copy(deep=True)
    settings.completed = True
    settings.steps.setdefault("environment", SetupStepStatus.DONE)
    await platform.save(settings)
    return await _state(request)
