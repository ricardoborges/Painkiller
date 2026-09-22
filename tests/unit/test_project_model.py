"""Unit tests for Project model with harness and api_key support."""

import pytest
from painkiller.core.domain.models import Project, HarnessType


def test_project_harness_default():
    p = Project(id="proj-1", name="Test", repo_path="/tmp/test")
    assert p.harness == HarnessType.AGY_SUPERPOWERS
    assert p.api_key is None
    assert p.masked_api_key is None


def test_project_custom_harness_and_masked_api_key():
    p = Project(
        id="proj-2",
        name="DeepSeek Proj",
        repo_path="/tmp/test2",
        harness=HarnessType.DEEPSEEK_SUPERPOWERS,
        api_key="sk-1234567890abcdef",
    )
    assert p.harness == HarnessType.DEEPSEEK_SUPERPOWERS
    assert p.api_key == "sk-1234567890abcdef"
    assert p.masked_api_key == "sk-***cdef"


def test_project_short_api_key_masked():
    p = Project(
        id="proj-3",
        name="Short Key",
        repo_path="/tmp/test3",
        api_key="secret",
    )
    assert p.masked_api_key == "******"


@pytest.mark.asyncio
async def test_sqlite_tracker_project_harness_persistence(tmp_path):
    from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker

    db_path = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    tracker = SQLiteIssueTracker(db_url=db_path)
    await tracker.init_db()

    # Default harness
    p1 = await tracker.create_project(name="Project 1", repo_path="/tmp/p1")
    assert p1.harness == HarnessType.AGY_SUPERPOWERS
    assert p1.api_key is None

    # Custom harness and api_key
    p2 = await tracker.create_project(
        name="Project 2",
        repo_path="/tmp/p2",
        harness=HarnessType.DEEPSEEK_SUPERPOWERS,
        api_key="sk-test-deepseek-123",
    )
    assert p2.harness == HarnessType.DEEPSEEK_SUPERPOWERS
    assert p2.api_key == "sk-test-deepseek-123"

    # Get from DB
    loaded = await tracker.get_project(p2.id)
    assert loaded is not None
    assert loaded.harness == HarnessType.DEEPSEEK_SUPERPOWERS
    assert loaded.api_key == "sk-test-deepseek-123"

    # Update project
    updated = await tracker.update_project(
        p2.id,
        harness=HarnessType.AGY_SUPERPOWERS,
        api_key="sk-new-key-456",
    )
    assert updated.harness == HarnessType.AGY_SUPERPOWERS
    assert updated.api_key == "sk-new-key-456"

    await tracker.close()

