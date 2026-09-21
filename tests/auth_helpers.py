"""Helpers for authenticating test clients against the API."""

from painkiller.api.security import BREAK_GLASS_ID, break_glass_fingerprint, issue_token


def admin_headers() -> dict[str, str]:
    """Bearer header for the break-glass admin (sees every project)."""
    return {"Authorization": f"Bearer {issue_token(BREAK_GLASS_ID, pw=break_glass_fingerprint())}"}


def user_headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(user_id)}"}
