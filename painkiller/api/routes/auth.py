"""Authentication routes: break-glass admin and Google sign-in."""

import logging
import secrets
import urllib.parse
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from painkiller.api.security import (
    AUTH_COOKIE_NAME,
    BREAK_GLASS_ID,
    OAUTH_STATE_KIND,
    _bearer,
    admin_account,
    break_glass_fingerprint,
    break_glass_user,
    check_break_glass,
    current_user,
    issue_token,
    user_payload,
    verify_token,
)
from painkiller.core.domain.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: Cookie que amarra o `state` do OAuth ao navegador que iniciou o login.
STATE_COOKIE = "pk_oauth_state"


class LoginRequest(BaseModel):
    username: str
    password: str


class FirstAccessRequest(BaseModel):
    username: str
    password: str


async def ensure_gitea_account(app, user: User) -> User:
    """Bind the user to a Gitea account, creating it on first need.

    Falha só é logada: sem Gitea o usuário ainda entra, e a próxima criação de
    projeto tenta de novo.
    """
    vcs = getattr(app.state, "vcs", None)
    if user.is_admin or user.gitea_username or vcs is None:
        return user
    google = getattr(app.state, "google_oauth", None)
    try:
        source_id = None
        if google is not None and google.enabled and user.google_sub:
            source_id = await vcs.ensure_google_auth_source(google.client_id, google.client_secret)
        gitea_username = await vcs.ensure_user(
            email=user.email,
            full_name=user.name,
            oauth_source_id=source_id,
            oauth_login_name=user.google_sub if source_id else None,
        )
    except Exception as e:
        logger.warning(f"Could not provision Gitea account for {user.email}: {e}")
        return user
    return await app.state.tracker.update_user(user.id, gitea_username=gitea_username)


@router.get("/config")
async def auth_config(request: Request):
    """What the login screen should offer."""
    google = getattr(request.app.state, "google_oauth", None)
    has_admin = admin_account() is not None
    return {
        "google": bool(google and google.enabled),
        "break_glass": has_admin,
        # Sem administrador, a única coisa que a plataforma oferece é criá-lo.
        "first_access": not has_admin,
    }


def admin_session(response: Response) -> dict:
    """Issue the administrator's token (bound to the current password) and set the cookie."""
    token = issue_token(BREAK_GLASS_ID, pw=break_glass_fingerprint())
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=7 * 86400,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"token": token, "user": user_payload(break_glass_user())}


@router.post("/login")
async def login(req: LoginRequest, response: Response):
    """Administrator login (the account created on the first access)."""
    if not check_break_glass(req.username, req.password):
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")
    return admin_session(response)


@router.post("/first-access")
async def first_access(req: FirstAccessRequest, request: Request, response: Response):
    """Create the administrator on a fresh install and sign them in.

    Só funciona enquanto não há administrador: depois disso responde 409.
    """
    from painkiller.api.platform import AdminAccountError

    if admin_account() is not None:
        raise HTTPException(status_code=409, detail="O primeiro acesso já foi feito. Entre com o administrador.")
    try:
        await request.app.state.platform.create_admin(req.username, req.password)
    except AdminAccountError as e:
        status = 409 if admin_account() is not None else 400
        raise HTTPException(status_code=status, detail=str(e))
    return admin_session(response)


@router.get("/me")
async def get_current_user(request: Request, response: Response, user: User = Depends(current_user)):
    token = _bearer(request)
    if token and request.cookies.get(AUTH_COOKIE_NAME) != token:
        response.set_cookie(
            AUTH_COOKIE_NAME,
            token,
            max_age=7 * 86400,
            httponly=True,
            samesite="lax",
            path="/",
        )
    return user_payload(user)


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/google/login")
async def google_login(request: Request):
    google = getattr(request.app.state, "google_oauth", None)
    if not google or not google.enabled:
        raise HTTPException(status_code=404, detail="Login com Google não está configurado")

    nonce = secrets.token_urlsafe(16)
    state = issue_token(nonce, kind=OAUTH_STATE_KIND, ttl_seconds=600)
    response = RedirectResponse(google.authorization_url(state), status_code=302)
    response.set_cookie(
        STATE_COOKIE,
        nonce,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=google.redirect_uri.startswith("https://"),
        path="/api/auth/google",
    )
    return response


def _back_to_login(fragment: dict, token: Optional[str] = None) -> RedirectResponse:
    # Fragmento, e não query: não vai para logs de servidor nem proxies.
    response = RedirectResponse(f"/login#{urllib.parse.urlencode(fragment)}", status_code=302)
    response.delete_cookie(STATE_COOKIE, path="/api/auth/google")
    if token:
        response.set_cookie(
            AUTH_COOKIE_NAME,
            token,
            max_age=7 * 86400,
            httponly=True,
            samesite="lax",
            path="/",
        )
    return response


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
):
    google = getattr(request.app.state, "google_oauth", None)
    if not google or not google.enabled:
        raise HTTPException(status_code=404, detail="Login com Google não está configurado")

    if error:
        return _back_to_login({"error": "Login com Google cancelado."})

    payload = verify_token(state, kind=OAUTH_STATE_KIND) if state else None
    cookie_nonce = request.cookies.get(STATE_COOKIE, "")
    if not payload or not cookie_nonce or not secrets.compare_digest(payload["sub"], cookie_nonce):
        return _back_to_login({"error": "Sessão de login expirada. Tente de novo."})
    if not code:
        return _back_to_login({"error": "O Google não devolveu o código de autorização."})

    try:
        identity = await google.fetch_identity(code)
    except Exception as e:
        logger.warning(f"Google sign-in failed: {e}")
        return _back_to_login({"error": "Não foi possível confirmar a conta Google."})

    sub = identity.get("sub")
    email = (identity.get("email") or "").strip().lower()
    if not sub or not email or not identity.get("email_verified", False):
        return _back_to_login({"error": "A conta Google precisa ter um e-mail verificado."})

    domains = google.allowed_domain_set
    if domains and email.rsplit("@", 1)[-1] not in domains:
        return _back_to_login({"error": "Este domínio de e-mail não tem acesso ao Painkiller."})

    tracker = request.app.state.tracker
    name = identity.get("name") or email
    user = await tracker.get_user_by_google_sub(sub)
    if user is None:
        user = await tracker.create_user(email=email, name=name, google_sub=sub)
    elif user.email != email or user.name != name:
        user = await tracker.update_user(user.id, email=email, name=name)

    user = await ensure_gitea_account(request.app, user)
    token = issue_token(user.id)
    return _back_to_login({"token": token}, token=token)
