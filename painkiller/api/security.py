"""Authentication tokens and per-user authorization for the HTTP API.

Dois tipos de usuário:

- **admin break-glass**: credenciais em `PAINKILLER_ADMIN_USER` /
  `PAINKILLER_ADMIN_PASSWORD`, não vive no banco e enxerga todos os projetos.
  É o acesso de emergência quando o login Google está fora.
- **usuário Google**: criado no primeiro login, dono dos próprios projetos e de
  uma conta no Gitea. Só enxerga o que é dele; o resto responde 404, para não
  revelar nem a existência.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Optional

from fastapi import Depends, HTTPException, Request

from painkiller.core.domain.models import Project, User, UserRole

logger = logging.getLogger(__name__)

#: Id fixo do admin break-glass nos tokens; usuários do banco são `user-<hex>`.
BREAK_GLASS_ID = "breakglass"

SESSION_KIND = "session"
OAUTH_STATE_KIND = "oauth_state"

# Sem PAINKILLER_AUTH_SECRET os tokens são assinados com uma chave efêmera:
# funciona, mas todo restart derruba as sessões.
_ephemeral_secret = secrets.token_urlsafe(32)
_warned_ephemeral = False


def _secret() -> bytes:
    global _warned_ephemeral
    configured = os.environ.get("PAINKILLER_AUTH_SECRET", "")
    if configured:
        return configured.encode("utf-8")
    if not _warned_ephemeral:
        logger.warning("PAINKILLER_AUTH_SECRET não definido: sessões serão perdidas a cada restart.")
        _warned_ephemeral = True
    return _ephemeral_secret.encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(subject: str, kind: str = SESSION_KIND, ttl_seconds: Optional[int] = None, **claims) -> str:
    """Sign a compact `payload.signature` token (HMAC-SHA256)."""
    if ttl_seconds is None:
        ttl_seconds = int(float(os.environ.get("PAINKILLER_AUTH_TOKEN_TTL_HOURS", "12")) * 3600)
    payload = {"sub": subject, "kind": kind, "exp": int(time.time()) + ttl_seconds, **claims}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def verify_token(token: str, kind: str = SESSION_KIND) -> Optional[dict]:
    """Return the payload of a valid, unexpired token of the given kind."""
    try:
        body, signature = token.split(".", 1)
        expected = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if payload.get("kind") != kind or int(payload.get("exp", 0)) < time.time():
        return None
    return payload


def break_glass_credentials() -> tuple[str, str]:
    return (
        os.environ.get("PAINKILLER_ADMIN_USER", "admin"),
        os.environ.get("PAINKILLER_ADMIN_PASSWORD", ""),
    )


def check_break_glass(username: str, password: str) -> bool:
    """Constant-time check; disabled while the password is empty."""
    expected_user, expected_password = break_glass_credentials()
    if not expected_password:
        return False
    user_ok = hmac.compare_digest(username.encode("utf-8"), expected_user.encode("utf-8"))
    pass_ok = hmac.compare_digest(password.encode("utf-8"), expected_password.encode("utf-8"))
    return user_ok and pass_ok


def break_glass_fingerprint() -> str:
    """Short hash of the admin password, carried in the admin's tokens."""
    password = break_glass_credentials()[1]
    return hmac.new(_secret(), password.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def break_glass_user() -> User:
    username, _ = break_glass_credentials()
    return User(id=BREAK_GLASS_ID, email=username, name="Administrador", role=UserRole.ADMIN)


def user_payload(user: User) -> dict:
    """What the UI gets from /login, /me and the Google callback."""
    return {
        "id": user.id,
        "username": user.email if not user.is_admin else break_glass_credentials()[0],
        "name": user.name or user.email,
        "email": user.email,
        "role": user.role.value,
        "gitea_username": user.gitea_username,
    }


AUTH_COOKIE_NAME = "painkiller_token"


def _bearer(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    cookie_val = request.cookies.get(AUTH_COOKIE_NAME)
    if cookie_val:
        return cookie_val
    # EventSource não manda cabeçalhos: os streams SSE levam o token na query.
    return request.query_params.get("token")


async def current_user(request: Request) -> User:
    """FastAPI dependency: the signed-in user, or 401."""
    cached = getattr(request.state, "user", None)
    if cached is not None:
        return cached

    token = _bearer(request)
    payload = verify_token(token) if token else None
    if not payload:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada")

    if payload["sub"] == BREAK_GLASS_ID:
        # Trocar (ou apagar) a senha no .env invalida os tokens emitidos com a anterior.
        if not break_glass_credentials()[1] or payload.get("pw") != break_glass_fingerprint():
            raise HTTPException(status_code=401, detail="Sessão inválida ou expirada")
        user = break_glass_user()
    else:
        user = await request.app.state.tracker.get_user(payload["sub"])
        if user is None:
            raise HTTPException(status_code=401, detail="Sessão inválida ou expirada")

    request.state.user = user
    return user


def can_see(user: User, project: Project) -> bool:
    return user.is_admin or (project.owner_id is not None and project.owner_id == user.id)


async def visible_project(request: Request, project_id: str) -> Project:
    """The project if the current user may see it; 404 otherwise (even if it exists)."""
    user = await current_user(request)
    project = await request.app.state.tracker.get_project(project_id)
    if project is None or not can_see(user, project):
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    return project


async def require_project(request: Request, project_id: str, user: User = Depends(current_user)) -> None:
    """Router dependency for every route with a `{project_id}` path parameter."""
    await visible_project(request, project_id)


async def require_task(request: Request, task_id: str, user: User = Depends(current_user)) -> None:
    """Router dependency for every route with a `{task_id}` path parameter."""
    if user.is_admin:
        return
    task = await request.app.state.tracker.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    await visible_project(request, task.project_id)


async def require_analysis(request: Request, session_id: str, user: User = Depends(current_user)) -> None:
    """Router dependency for `/api/analysis/{session_id}` routes."""
    if user.is_admin:
        return
    session = await request.app.state.tracker.get_analysis_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sessão de análise não encontrada")
    await visible_project(request, session.project_id)


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Apenas o administrador pode fazer isso")
    return user
