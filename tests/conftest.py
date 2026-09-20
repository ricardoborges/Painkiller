"""Pytest configuration and global test fixtures."""

import pytest
import asyncio

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"
