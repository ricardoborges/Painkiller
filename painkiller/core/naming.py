"""Utilities for deterministic, safe slug and identity composition across Painkiller, VCS, and deployment."""

import re
import secrets
import unicodedata
from dataclasses import dataclass
from typing import Optional

from painkiller.core.domain.models import User


def slugify(text: str, max_length: int = 24) -> str:
    """Normalize text into a lowercase alphanumeric hyphenated slug safe for DNS and URLs."""
    if not text:
        return ""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    # Replace dots, spaces, underscores, and slashes with hyphens
    hyphenated = re.sub(r"[._\s/]+", "-", ascii_text)
    # Strip any character that is not alphanumeric or hyphen
    cleaned = re.sub(r"[^a-zA-Z0-9-]", "", hyphenated).strip("-").lower()
    # Collapse multiple hyphens
    slug = re.sub(r"-+", "-", cleaned)
    return slug[:max_length].rstrip("-")


def get_user_slug(user: Optional[User]) -> str:
    """Extract a clean, URL/DNS-safe slug identifying the user."""
    if not user or user.is_admin:
        return "admin"
    if user.gitea_username:
        slug = slugify(user.gitea_username, max_length=14)
        if slug:
            return slug
    if user.email:
        local = user.email.split("@", 1)[0]
        slug = slugify(local, max_length=14)
        if slug:
            return slug
    if user.name:
        slug = slugify(user.name, max_length=14)
        if slug:
            return slug
    return "user"


@dataclass(frozen=True)
class ProjectIdentity:
    user_slug: str
    name_slug: str
    code: str
    slug: str
    project_id: str


def compose_project_identity(
    user: Optional[User],
    project_name: str,
    code: Optional[str] = None,
) -> ProjectIdentity:
    """
    Generate a composite project identity ensuring uniqueness across VCS (Gitea) and Deployments (Coolify).

    Pattern:
      user_slug: max 14 chars (e.g. 'ricardo', 'admin')
      name_slug: max 20 chars (e.g. 'loja-virtual')
      code: 6 hex chars (e.g. 'a1b2c3')
      slug: {user_slug}-{name_slug}-{code} (e.g. 'ricardo-loja-virtual-a1b2c3')
      project_id: proj-{slug} (e.g. 'proj-ricardo-loja-virtual-a1b2c3')
    """
    user_slug = get_user_slug(user)
    name_slug = slugify(project_name, max_length=20) or "proj"
    unique_code = (code or secrets.token_hex(3)).lower()[:6]
    slug = f"{user_slug}-{name_slug}-{unique_code}"
    project_id = f"proj-{slug}"

    return ProjectIdentity(
        user_slug=user_slug,
        name_slug=name_slug,
        code=unique_code,
        slug=slug,
        project_id=project_id,
    )
