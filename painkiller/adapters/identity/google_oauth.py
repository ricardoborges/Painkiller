"""Google OAuth 2.0 (OpenID Connect) client for the sign-in flow."""

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
        allowed_domains: Optional[str] = None,
    ):
        # Vazio até PlatformConfig aplicar o que o admin salvou no wizard.
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        self.redirect_uri = redirect_uri or "http://localhost:8000/api/auth/google/callback"
        self.allowed_domains = allowed_domains or ""

    def configure(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        allowed_domains: str = "",
    ) -> None:
        """Apply settings saved in the setup wizard; takes effect on the next sign-in."""
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.allowed_domains = allowed_domains

    @property
    def allowed_domain_set(self) -> set[str]:
        raw = self.allowed_domains or ""
        return {d.strip().lower().lstrip("@") for d in raw.split(",") if d.strip()}

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
