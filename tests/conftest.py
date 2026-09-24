"""Pytest configuration and global test fixtures."""

import pytest
import asyncio

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def isolate_test_storage(tmp_path, monkeypatch):
    """Ensure tests create projects inside an isolated temporary directory."""
    test_storage = tmp_path / "storage"
    test_storage.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PAINKILLER_STORAGE_DIR", str(test_storage))
    return test_storage



#: Credenciais do administrador nos testes; o hash é calculado uma vez (scrypt é lento de propósito).
TEST_ADMIN = ("admin", "test-admin-password")
_TEST_ADMIN_HASH = None


@pytest.fixture(autouse=True)
def frozen_admin(monkeypatch):
    """Deterministic signing key and administrator, whatever each test database holds.

    Em produção PlatformConfig instala os dois a partir do banco; aqui os
    setters viram no-op para que cada create_app (com banco novo e vazio) não
    apague o administrador que `admin_headers()` assina. Os testes do primeiro
    acesso sobrescrevem esta fixture para exercitar o fluxo real.
    """
    global _TEST_ADMIN_HASH
    from painkiller.api import security

    if _TEST_ADMIN_HASH is None:
        _TEST_ADMIN_HASH = security.hash_password(TEST_ADMIN[1])
    monkeypatch.setattr(security, "_auth_secret", b"test-auth-secret")
    monkeypatch.setattr(security, "_admin", (TEST_ADMIN[0], _TEST_ADMIN_HASH))
    monkeypatch.setattr(security, "set_auth_secret", lambda value: None)
    monkeypatch.setattr(security, "set_admin_account", lambda username, password_hash: None)
