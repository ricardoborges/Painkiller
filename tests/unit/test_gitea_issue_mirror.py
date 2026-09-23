"""Unit tests for the tracker decorator that mirrors tasks into Gitea issues.

The real SQLite tracker sits underneath (tasks, projects and the new issue
columns are what is under test); Gitea is a recording fake.
"""

import pytest

from painkiller.adapters.issue_trackers.gitea_mirror import (
    MAX_COMMENT_CHARS,
    GiteaIssueMirror,
    label_name,
)
from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker
from painkiller.core.domain.models import TaskStatus

REPO_URL = "http://gitea.test/ana/jogo-de-damas"


class FakeGitea:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.issues: dict[int, dict] = {}
        self.comments: list[tuple[int, str]] = []
        self.label_calls = 0

    def repo_from_url(self, url):
        prefix = "http://gitea.test/"
        if not url or not url.startswith(prefix):
            return None
        owner, repo = url[len(prefix):].split("/")
        return owner, repo

    async def ensure_labels(self, owner, repo, specs):
        if self.fail:
            raise RuntimeError("gitea fora do ar")
        self.label_calls += 1
        return {spec["name"]: i for i, spec in enumerate(specs, start=1)}

    async def create_issue(self, owner, repo, title, body, label_ids):
        number = len(self.issues) + 1
        self.issues[number] = {"title": title, "body": body, "labels": label_ids, "closed": False}
        return {"number": number, "html_url": f"http://gitea.test/{owner}/{repo}/issues/{number}"}

    async def update_issue(self, owner, repo, number, *, title=None, body=None, closed=None, label_ids=None):
        issue = self.issues[number]
        issue.update({k: v for k, v in {"title": title, "body": body, "closed": closed, "labels": label_ids}.items() if v is not None})

    async def comment_issue(self, owner, repo, number, body):
        self.comments.append((number, body))


@pytest.fixture
async def setup(tmp_path):
    inner = SQLiteIssueTracker(db_url=f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    await inner.init_db()
    gitea = FakeGitea()
    mirror = GiteaIssueMirror(inner, gitea)
    project = await mirror.create_project(name="Damas", repo_path=str(tmp_path / "repo"), description="d")
    project = await mirror.update_project(project.id, repo_url=REPO_URL)
    yield mirror, gitea, project
    await mirror.close()


def _status_label(gitea, status):
    # FakeGitea numera os rótulos na ordem de STATUS_LABELS.
    from painkiller.adapters.issue_trackers.gitea_mirror import label_specs

    return [i for i, spec in enumerate(label_specs(), start=1) if spec["name"] == label_name(status)]


async def test_new_task_becomes_an_issue_with_checklist_and_status_label(setup):
    mirror, gitea, project = setup

    task = await mirror.create_task(
        project_id=project.id, title="Tabuleiro", description="Desenhar o tabuleiro",
        acceptance_criteria=["8x8", "casas alternadas"], target_files=["index.html"],
    )
    await mirror.drain()

    stored = await mirror.get_task(task.id)
    assert stored.issue_number == 1
    assert stored.issue_url == "http://gitea.test/ana/jogo-de-damas/issues/1"
    issue = gitea.issues[1]
    assert issue["title"] == "Tabuleiro"
    assert "- [ ] 8x8" in issue["body"] and "`index.html`" in issue["body"]
    assert issue["labels"] == _status_label(gitea, TaskStatus.BACKLOG)


async def test_status_changes_move_the_label_and_completion_closes(setup):
    mirror, gitea, project = setup
    task = await mirror.create_task(project_id=project.id, title="T", description="d", acceptance_criteria=["ok"])
    await mirror.update_task_status(task.id, TaskStatus.AWAITING_ANALYST)
    await mirror.drain()
    assert gitea.issues[1]["labels"] == _status_label(gitea, TaskStatus.AWAITING_ANALYST)
    assert gitea.issues[1]["closed"] is False

    await mirror.update_task_status(task.id, TaskStatus.COMPLETED)
    await mirror.drain()
    assert gitea.issues[1]["closed"] is True
    assert "- [x] ok" in gitea.issues[1]["body"]
    # Só uma criação: as mudanças de estado editam a mesma issue.
    assert len(gitea.issues) == 1


async def test_dependencies_link_to_the_other_issue(setup):
    mirror, gitea, project = setup
    first = await mirror.create_task(project_id=project.id, title="Base", description="d")
    await mirror.drain()
    second = await mirror.create_task(project_id=project.id, title="Peças", description="d", dependencies=[first.id])
    await mirror.drain()
    assert "#1 Base" in gitea.issues[2]["body"]


async def test_comments_are_mirrored_and_long_logs_truncated(setup):
    mirror, gitea, project = setup
    task = await mirror.create_task(project_id=project.id, title="T", description="d")
    await mirror.add_comment(task.id, "analyst", "Use damas brasileiras")
    await mirror.add_comment(task.id, "system", "❌ falhou\n" + "x" * (MAX_COMMENT_CHARS * 3))
    await mirror.drain()

    assert gitea.comments[0] == (1, "**Analista:** Use damas brasileiras")
    long_body = gitea.comments[1][1]
    assert "<details>" in long_body and len(long_body) < MAX_COMMENT_CHARS + 1000


async def test_gitea_failure_never_breaks_the_task_write(tmp_path):
    inner = SQLiteIssueTracker(db_url=f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    await inner.init_db()
    mirror = GiteaIssueMirror(inner, FakeGitea(fail=True))
    project = await mirror.create_project(name="Damas", repo_path=str(tmp_path / "repo"), description="d")
    await mirror.update_project(project.id, repo_url=REPO_URL)

    task = await mirror.create_task(project_id=project.id, title="T", description="d")
    updated = await mirror.update_task_status(task.id, TaskStatus.READY)
    await mirror.drain()

    assert updated.status == TaskStatus.READY
    assert (await mirror.get_task(task.id)).issue_number is None
    await mirror.close()


async def test_project_without_gitea_repo_is_left_alone(tmp_path):
    inner = SQLiteIssueTracker(db_url=f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    await inner.init_db()
    gitea = FakeGitea()
    mirror = GiteaIssueMirror(inner, gitea)
    project = await mirror.create_project(name="Local", repo_path=str(tmp_path / "repo"), description="d")

    await mirror.create_task(project_id=project.id, title="T", description="d")
    await mirror.drain()

    assert gitea.issues == {} and gitea.label_calls == 0
    assert (await mirror.sync_project(project.id))["enabled"] is False
    await mirror.close()


async def test_sync_project_backfills_tasks_created_before_the_mirror(tmp_path):
    inner = SQLiteIssueTracker(db_url=f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    await inner.init_db()
    project = await inner.create_project(name="Damas", repo_path=str(tmp_path / "repo"), description="d")
    await inner.update_project(project.id, repo_url=REPO_URL)
    # Tarefas antigas, escritas direto no tracker (sem espelho).
    base = await inner.create_task(project_id=project.id, title="Base", description="d")
    later = await inner.create_task(project_id=project.id, title="Peças", description="d", dependencies=[base.id])
    await inner.update_task_status(base.id, TaskStatus.COMPLETED)

    gitea = FakeGitea()
    mirror = GiteaIssueMirror(inner, gitea)
    result = await mirror.sync_project(project.id)

    assert result == {"enabled": True, "created": 2, "updated": 2}
    assert gitea.issues[1]["closed"] is True
    # Na segunda passada a dependência já aponta para a issue criada.
    assert "#1 Base" in gitea.issues[2]["body"]
    assert (await mirror.sync_project(project.id))["created"] == 0
    await mirror.close()
