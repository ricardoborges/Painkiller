"""Unit tests for naming and project identity composition."""

import pytest
from painkiller.core.domain.models import User, UserRole
from painkiller.core.naming import (
    slugify,
    get_user_slug,
    compose_project_identity,
)


def test_slugify_basic_and_accents():
    assert slugify("Meu Projeto Incrível!") == "meu-projeto-incrivel"
    assert slugify("  espaços   e   -- hífens __ ") == "espacos-e-hifens"
    assert slugify("ÁÉÍÓÚ çãõ") == "aeiou-cao"
    assert slugify("") == ""


def test_slugify_max_length():
    long_name = "a" * 50
    slug = slugify(long_name, max_length=20)
    assert len(slug) == 20
    assert slug == "a" * 20


def test_get_user_slug_admin():
    admin = User(id="usr-1", email="admin@corp.com", name="Admin Master", role=UserRole.ADMIN)
    assert get_user_slug(admin) == "admin"
    assert get_user_slug(None) == "admin"


def test_get_user_slug_gitea_username():
    user = User(
        id="usr-2",
        email="ricardo@corp.com",
        name="Ricardo Borges",
        role=UserRole.USER,
        gitea_username="ricardoborges",
    )
    assert get_user_slug(user) == "ricardoborges"


def test_get_user_slug_email_fallback():
    user = User(
        id="usr-3",
        email="maria.silva@corp.com",
        name="",
        role=UserRole.USER,
        gitea_username=None,
    )
    assert get_user_slug(user) == "maria-silva"


def test_get_user_slug_name_fallback():
    user = User(
        id="usr-4",
        email="",
        name="João da Silva",
        role=UserRole.USER,
        gitea_username=None,
    )
    assert get_user_slug(user) == "joao-da-silva"


def test_compose_project_identity_deterministic_code():
    user = User(
        id="usr-10",
        email="ricardo@corp.com",
        gitea_username="ricardo",
        role=UserRole.USER,
    )
    identity = compose_project_identity(user, "Loja Virtual", code="a1b2c3")

    assert identity.user_slug == "ricardo"
    assert identity.name_slug == "loja-virtual"
    assert identity.code == "a1b2c3"
    assert identity.slug == "ricardo-loja-virtual-a1b2c3"
    assert identity.project_id == "proj-ricardo-loja-virtual-a1b2c3"


def test_compose_project_identity_random_code_uniqueness():
    user = User(
        id="usr-10",
        email="ricardo@corp.com",
        gitea_username="ricardo",
        role=UserRole.USER,
    )
    id1 = compose_project_identity(user, "App")
    id2 = compose_project_identity(user, "App")

    assert id1.project_id != id2.project_id
    assert id1.slug != id2.slug
    assert len(id1.code) == 6
    assert id1.project_id.startswith("proj-ricardo-app-")
    assert id2.project_id.startswith("proj-ricardo-app-")


def test_compose_project_identity_for_admin():
    admin = User(id="usr-admin", email="admin@corp.com", role=UserRole.ADMIN)
    identity = compose_project_identity(admin, "Sistema de Cobrança", code="9f8e7d")

    assert identity.user_slug == "admin"
    assert identity.slug == "admin-sistema-de-cobranca-9f8e7d"
    assert identity.project_id == "proj-admin-sistema-de-cobranca-9f8e7d"
