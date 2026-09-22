"""Reverse proxy router for seamless zero-click SSO with Gitea."""

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from painkiller.api.security import (
    BREAK_GLASS_ID,
    _bearer,
    verify_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vcs-proxy"])

#: Hop-by-hop headers that should not be forwarded
EXCLUDED_REQUEST_HEADERS = {
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "upgrade",
}

EXCLUDED_RESPONSE_HEADERS = {
    "transfer-encoding",
    "connection",
    "content-length",
    "content-encoding",
}


def _get_gitea_internal_url() -> str:
    return os.environ.get("PAINKILLER_GITEA_INTERNAL_URL", "http://gitea:3000").rstrip("/")


async def _resolve_gitea_identity(request: Request) -> tuple[Optional[str], Optional[str]]:
    """Resolve (gitea_username, email) from the incoming Painkiller session, if any."""
    token = _bearer(request)
    if not token:
        return None, None
    payload = verify_token(token)
    if not payload:
        return None, None

    if payload.get("sub") == BREAK_GLASS_ID:
        admin_user = os.environ.get("PAINKILLER_GITEA_USER", "painkiller")
        admin_email = os.environ.get("PAINKILLER_GITEA_EMAIL", "bot@painkiller.local")
        return admin_user, admin_email

    tracker = getattr(request.app.state, "tracker", None)
    if tracker is None:
        return None, None

    try:
        user = await tracker.get_user(payload["sub"])
        if user and user.gitea_username:
            return user.gitea_username, user.email
    except Exception as e:
        logger.debug(f"Could not resolve user for Gitea proxy: {e}")

    return None, None


def _get_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=120.0, follow_redirects=False)


@router.api_route("/gitea", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"], include_in_schema=False)
@router.api_route("/gitea/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"], include_in_schema=False)
async def gitea_reverse_proxy(request: Request, path: str = ""):
    """Proxy requests to internal Gitea with X-WEBAUTH-USER authentication."""
    base_url = _get_gitea_internal_url()
    target_url = f"{base_url}/{path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    # Build upstream request headers
    forward_headers = {}
    for key, value in request.headers.items():
        if key.lower() not in EXCLUDED_REQUEST_HEADERS:
            forward_headers[key] = value

    # Always override X-WEBAUTH-* headers from client to prevent spoofing
    forward_headers.pop("x-webauth-user", None)
    forward_headers.pop("x-webauth-email", None)

    # Inject identity from verified Painkiller session
    auth_user, auth_email = await _resolve_gitea_identity(request)
    if auth_user:
        forward_headers["X-WEBAUTH-USER"] = auth_user
        if auth_email:
            forward_headers["X-WEBAUTH-EMAIL"] = auth_email

    # Forward request to upstream Gitea
    client = _get_http_client()
    try:
        req_stream = client.build_request(
            method=request.method,
            url=target_url,
            headers=forward_headers,
            content=request.stream(),
        )
        upstream_resp = await client.send(req_stream, stream=True)
    except Exception as e:
        await client.aclose()
        logger.warning(f"Error connecting to Gitea upstream at {target_url}: {e}")
        return Response(content=f"Gitea upstream unavailable: {e}", status_code=502)

    # Build client response headers
    client_headers = {}
    for key, value in upstream_resp.headers.items():
        if key.lower() not in EXCLUDED_RESPONSE_HEADERS:
            client_headers[key] = value

    async def _body_stream():
        try:
            if upstream_resp.is_stream_consumed:
                yield upstream_resp.content
            else:
                async for chunk in upstream_resp.aiter_bytes():
                    yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    response = StreamingResponse(
        _body_stream(),
        status_code=upstream_resp.status_code,
        headers=client_headers,
    )

    # Forward all Set-Cookie headers properly
    cookie_headers = upstream_resp.headers.get_list("set-cookie")
    for cookie in cookie_headers:
        response.headers.append("set-cookie", cookie)

    return response
