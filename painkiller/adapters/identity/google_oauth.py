"""Google OAuth 2.0 (OpenID Connect) client for the sign-in flow."""

import os
import urllib.parse
from typing import Optional

import httpx

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


class GoogleIdentity(dict):
    """Claims returned by Google's userinfo endpoint (`sub`, `email`, `name`...)."""


class GoogleOAuthClient:
    """Authorization Code flow against Google, done server-side.

    O `code` é trocado direto com o Google por TLS e os dados do usuário vêm do
    endpoint userinfo com o access token recém-emitido, então não é preciso
    validar a assinatura do id_token localmente.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ):
        self.client_id = client_id if client_id is not None else os.environ.get("PAINKILLER_GOOGLE_CLIENT_ID", "")
        self.client_secret = (
            client_secret if client_secret is not None else os.environ.get("PAINKILLER_GOOGLE_CLIENT_SECRET", "")
        )
        public_url = os.environ.get("PAINKILLER_PUBLIC_URL", "http://localhost:8000").rstrip("/")
        self.redirect_uri = redirect_uri or os.environ.get(
            "PAINKILLER_GOOGLE_REDIRECT_URI", f"{public_url}/api/auth/google/callback"
        )

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def authorization_url(self, state: str) -> str:
        query = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
        return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(query)}"

    async def fetch_identity(self, code: str) -> GoogleIdentity:
        """Exchange the authorization code and return the user's claims."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_res = await client.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if token_res.status_code != 200:
                raise RuntimeError(f"Google token exchange failed: {token_res.status_code} - {token_res.text}")
            access_token = token_res.json().get("access_token")
            if not access_token:
                raise RuntimeError("Google token exchange returned no access_token")

            info_res = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
            if info_res.status_code != 200:
                raise RuntimeError(f"Google userinfo failed: {info_res.status_code} - {info_res.text}")
            return GoogleIdentity(info_res.json())
