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

