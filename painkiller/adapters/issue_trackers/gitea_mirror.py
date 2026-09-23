"""Mirror backlog tasks into Gitea issues, as a decorator over the tracker.

Every task write in Painkiller goes through five tracker methods, so wrapping
the tracker is the one place where nothing slips past: the engine and the
routes keep talking to `IssueTrackerPort` and never learn Gitea exists.

The mirror is one-way. Painkiller owns the task; the issue shows it — status as
an exclusive scoped label (`painkiller/…`), open/closed state, acceptance
criteria as a checklist, dependencies as `#n` links, and the task's comments.
Edits made in Gitea do not flow back.

Gitea is never on the critical path: each mirror call runs in the background,
serialized per task (the issue must exist before its labels change), and a
failure is logged, never raised — dispatch cannot stall because Gitea is slow
or down.
"""

import asyncio
import logging
from typing import Any, Optional

from painkiller.core.domain.models import Project, Task, TaskStatus

logger = logging.getLogger(__name__)

LABEL_SCOPE = "painkiller"

#: Um rótulo por estado, exclusivo no escopo: a issue nunca tem dois estados.
#: Mesma regra de cor da UI — o vermelhão só significa "agente esperando o
#: analista" (exit 42); o resto é tinta em tons de cinza.
STATUS_LABELS: dict[TaskStatus, dict[str, str]] = {
    TaskStatus.BACKLOG: {"name": "backlog", "color": "#d3d3d8", "description": "Ainda não liberada para execução"},
    TaskStatus.READY: {"name": "pronta", "color": "#8b8b93", "description": "Pronta para o agente"},
    TaskStatus.RUNNING: {"name": "executando", "color": "#55555c", "description": "Agente trabalhando na branch da tarefa"},
    TaskStatus.AWAITING_ANALYST: {
        "name": "aguardando-analista",
        "color": "#cc3a1e",
        "description": "Agente parado esperando resposta do analista",
    },
    TaskStatus.IN_REVIEW: {"name": "em-revisao", "color": "#55555c", "description": "Implementada, aguardando revisão"},
    TaskStatus.FAILED: {"name": "falhou", "color": "#141416", "description": "Execução ou testes falharam"},
    TaskStatus.COMPLETED: {"name": "concluida", "color": "#8b8b93", "description": "Testada e incorporada"},
}

#: Comentários longos (logs de execução) viram um trecho recolhível no fim.
MAX_COMMENT_CHARS = 4000


def label_name(status: TaskStatus) -> str:
    return f"{LABEL_SCOPE}/{STATUS_LABELS[status]['name']}"


def label_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": label_name(status),
            "color": spec["color"],
            "description": spec["description"],
            "exclusive": True,
        }
        for status, spec in STATUS_LABELS.items()
    ]


def issue_body(task: Task, dependency_refs: list[str]) -> str:
    """Markdown body of the issue; rebuilt on every sync so it tracks the task."""
    done = task.status == TaskStatus.COMPLETED
    parts = [task.description.strip() or "_Sem descrição._"]
    if task.acceptance_criteria:
        mark = "x" if done else " "
        parts.append("### Critérios de aceite\n" + "\n".join(f"- [{mark}] {c}" for c in task.acceptance_criteria))
    if task.target_files:
        parts.append("### Arquivos-alvo\n" + "\n".join(f"- `{f}`" for f in task.target_files))
    if dependency_refs:
        parts.append("### Depende de\n" + "\n".join(f"- {ref}" for ref in dependency_refs))
    branch = task.assigned_branch or f"feature/{task.id}"
    parts.append(
        "---\n"
        f"<sub>Tarefa `{task.id}` · branch `{branch}` · espelhada pelo Painkiller. "
        "O estado é gerido lá; edições feitas aqui não voltam.</sub>"
    )
    return "\n\n".join(parts)


def comment_body(author: str, comment: str) -> str:
    who = {"system": "Painkiller", "analyst": "Analista"}.get(author, author)
    text = comment.strip()
    if len(text) <= MAX_COMMENT_CHARS:
        return f"**{who}:** {text}"
    head, _, _ = text.partition("\n")
    tail = text[-MAX_COMMENT_CHARS:]
    return (
        f"**{who}:** {head[:500]}\n\n"
        f"<details><summary>Saída completa truncada — últimos {MAX_COMMENT_CHARS} caracteres</summary>\n\n"
        f"```text\n{tail}\n```\n</details>"
    )


class GiteaIssueMirror:
    """Tracker decorator: delegates everything, mirrors task writes to Gitea issues."""

    def __init__(self, inner: Any, vcs: Any):
        self._inner = inner
        self._vcs = vcs
        self._labels: dict[tuple[str, str], dict[str, int]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._pending: set[asyncio.Task] = set()

    def __getattr__(self, name: str) -> Any:
        # Só é chamado para o que esta classe não define: o resto do tracker
        # (projetos, sessões, uso, usuários) passa direto.
        return getattr(self._inner, name)

    # ---- escritas espelhadas ---------------------------------------------

    async def create_task(self, *args, **kwargs) -> Task:
        task = await self._inner.create_task(*args, **kwargs)
        self._spawn(task.id, self._sync_task(task.id))
        return task

    async def update_task_status(self, task_id: str, *args, **kwargs) -> Task:
        task = await self._inner.update_task_status(task_id, *args, **kwargs)
        self._spawn(task_id, self._sync_task(task_id))
        return task

    async def add_comment(self, task_id: str, author: str, comment: str) -> None:
        await self._inner.add_comment(task_id, author, comment)
        self._spawn(task_id, self._comment(task_id, author, comment))

    # ---- sincronização ----------------------------------------------------

    async def sync_project(self, project_id: str) -> dict[str, Any]:
        """Backfill: create missing issues and realign every existing one.

        Duas passadas: primeiro todas as issues existem, depois os corpos são
        refeitos, para que as dependências já apareçam como `#n`.
        """
        await self.drain()
        project = await self._inner.get_project(project_id)
        repo = self._repo_of(project)
        if repo is None:
            return {"enabled": False, "created": 0, "updated": 0}
        tasks = sorted(await self._inner.list_tasks(project_id), key=lambda t: t.created_at)
        created = 0
        for task in tasks:
            if task.issue_number is None:
                if await self._with_lock(task.id, self._ensure_issue(task, project, repo)) is not None:
                    created += 1
        for task in tasks:
            await self._with_lock(task.id, self._sync_task(task.id))
        return {"enabled": True, "created": created, "updated": len(tasks)}

    async def drain(self) -> None:
        """Wait for background mirror calls (tests and backfill)."""
        while self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)

    async def close(self) -> None:
        # O espelho lê o banco em segundo plano: termina antes de ele fechar.
        await self.drain()
        await self._inner.close()

    def _spawn(self, task_id: str, coro) -> None:
        job = asyncio.create_task(self._with_lock(task_id, coro))
        self._pending.add(job)
        job.add_done_callback(self._pending.discard)

    async def _with_lock(self, task_id: str, coro) -> Any:
        lock = self._locks.setdefault(task_id, asyncio.Lock())
        async with lock:
            try:
                return await coro
            except Exception as e:
                logger.warning(f"Gitea: espelhamento da tarefa {task_id} falhou: {e}")
                return None

    def _repo_of(self, project: Optional[Project]) -> Optional[tuple[str, str]]:
        if not isinstance(project, Project):
            return None
        return self._vcs.repo_from_url(project.repo_url)

    async def _label_ids(self, repo: tuple[str, str]) -> dict[str, int]:
        if repo not in self._labels:
            self._labels[repo] = await self._vcs.ensure_labels(*repo, label_specs())
        return self._labels[repo]

    async def _dependency_refs(self, task: Task) -> list[str]:
        refs = []
        for dep_id in task.dependencies:
            dep = await self._inner.get_task(dep_id)
            if dep is not None and dep.issue_number is not None:
                refs.append(f"#{dep.issue_number} {dep.title}")
            else:
                refs.append(f"`{dep_id}`")
        return refs

    async def _ensure_issue(self, task: Task, project: Project, repo: tuple[str, str]) -> Task:
        if task.issue_number is not None:
            return task
        labels = await self._label_ids(repo)
        issue = await self._vcs.create_issue(
            *repo,
            title=task.title,
            body=issue_body(task, await self._dependency_refs(task)),
            label_ids=[labels[label_name(task.status)]],
        )
        return await self._inner.set_task_issue(task.id, issue["number"], issue["html_url"])

    async def _sync_task(self, task_id: str) -> None:
        task = await self._inner.get_task(task_id)
        if task is None:
            return
        project = await self._inner.get_project(task.project_id)
        repo = self._repo_of(project)
        if repo is None:
            return
        if task.issue_number is None:
            await self._ensure_issue(task, project, repo)
            return
        labels = await self._label_ids(repo)
        await self._vcs.update_issue(
            *repo,
            task.issue_number,
            title=task.title,
            body=issue_body(task, await self._dependency_refs(task)),
            closed=task.status == TaskStatus.COMPLETED,
            label_ids=[labels[label_name(task.status)]],
        )

    async def _comment(self, task_id: str, author: str, comment: str) -> None:
        task = await self._inner.get_task(task_id)
        if task is None:
            return
        project = await self._inner.get_project(task.project_id)
        repo = self._repo_of(project)
        if repo is None:
            return
        if task.issue_number is None:
            task = await self._ensure_issue(task, project, repo)
        await self._vcs.comment_issue(*repo, task.issue_number, comment_body(author, comment))
