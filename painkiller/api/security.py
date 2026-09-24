"""Authentication tokens and per-user authorization for the HTTP API.

Dois tipos de usuário:

- **administrador**: criado no primeiro acesso à plataforma e guardado nas
  configurações da plataforma (SQLite), com a senha em hash scrypt. Enxerga
  todos os projetos e continua sendo o acesso de emergência quando o login
  Google está fora.
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

# Chave de assinatura e conta do administrador, instaladas por PlatformConfig a
# partir do banco na subida. Até lá (ou sem banco) a chave é efêmera e não há
# administrador, o que só acontece antes do primeiro acesso.
_auth_secret: bytes = secrets.token_urlsafe(32).encode("utf-8")
_admin: Optional[tuple[str, str]] = None

#: Parâmetros do scrypt: ~16 MB e algumas dezenas de ms por verificação.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def set_auth_secret(value: str) -> None:
    """Install the token-signing key (kept in the database)."""
    global _auth_secret
    _auth_secret = value.encode("utf-8")


def set_admin_account(username: Optional[str], password_hash: Optional[str]) -> None:
    """Install the administrator account; None = first access still pending."""
    global _admin
    _admin = (username, password_hash) if username and password_hash else None


def admin_account() -> Optional[tuple[str, str]]:
    """(username, password_hash), or None before the first access."""
    return _admin


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=_unb64(salt), n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, _unb64(digest))


def _secret() -> bytes:
    return _auth_secret


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


def check_break_glass(username: str, password: str) -> bool:
    """Check the administrator's credentials; always False before the first access."""
    account = admin_account()
    if account is None:
        return False
    expected_user, password_hash = account
    user_ok = hmac.compare_digest(username.strip().encode("utf-8"), expected_user.encode("utf-8"))
    # Verifica a senha mesmo com usuário errado, para não vazar qual dos dois falhou pelo tempo.
    pass_ok = verify_password(password, password_hash)
    return user_ok and pass_ok


def break_glass_fingerprint() -> str:
    """Short hash of the stored password hash, carried in the admin's tokens.

    Trocar a senha muda o hash (e o sal), o que invalida os tokens anteriores.
    """
    account = admin_account()
    material = account[1] if account else ""
    return hmac.new(_secret(), material.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def break_glass_user() -> User:
    account = admin_account()
    username = account[0] if account else "admin"
    return User(id=BREAK_GLASS_ID, email=username, name="Administrador", role=UserRole.ADMIN)


def user_payload(user: User) -> dict:
    """What the UI gets from /login, /me and the Google callback."""
    return {
        "id": user.id,
        "username": user.email,
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
        # Trocar a senha (ou zerar a conta) invalida os tokens emitidos com a anterior.
        if admin_account() is None or payload.get("pw") != break_glass_fingerprint():
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
