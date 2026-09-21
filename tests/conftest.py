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



@pytest.fixture(autouse=True)
def isolate_auth_env(monkeypatch):
    """Deterministic credentials, independent of whatever the local .env holds."""
    monkeypatch.setenv("PAINKILLER_ADMIN_USER", "admin")
    monkeypatch.setenv("PAINKILLER_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("PAINKILLER_AUTH_SECRET", "test-auth-secret")
    monkeypatch.setenv("PAINKILLER_GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("PAINKILLER_GOOGLE_CLIENT_SECRET", "")
    monkeypatch.delenv("PAINKILLER_GOOGLE_ALLOWED_DOMAINS", raising=False)
