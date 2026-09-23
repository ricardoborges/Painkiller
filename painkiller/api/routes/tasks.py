"""Task routes."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from painkiller.api.security import require_task
from painkiller.core.domain.models import AgentEvent, AgentEventType

# Toda rota daqui tem {task_id}: a checagem de dono vale para o router inteiro.
router = APIRouter(prefix="/api/tasks", tags=["tasks"], dependencies=[Depends(require_task)])


class ClarificationReplyRequest(BaseModel):
    answer: str


@router.get("/{task_id}")
async def get_task(task_id: str, request: Request):
    tracker = request.app.state.tracker
    task = await tracker.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/{task_id}/dispatch")
async def dispatch_task(task_id: str, request: Request):
    orchestrator = request.app.state.orchestrator
    try:
        updated_task = await orchestrator.dispatch_task(task_id)
        return updated_task
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{task_id}/stop")
async def stop_task(task_id: str, request: Request):
    orchestrator = request.app.state.orchestrator
    try:
        await orchestrator.stop_task(task_id)
        return {"status": "stopping", "task_id": task_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Chaves onde o stream-json costuma pôr o alvo de uma ferramenta (comando,
# arquivo). O formato do `agy` não é contrato estável: sem acerto, fica só o nome.
_TOOL_DETAIL_KEYS = (
    "command", "CommandLine", "cmd", "file_path", "path", "AbsolutePath",
    "TargetFile", "pattern", "query", "url", "description",
)


def _tool_detail(raw: dict) -> Optional[str]:
    step = raw.get("step_update") or {}
    candidates = [step.get(k) for k in ("tool_input", "input", "args", "arguments", "parameters")]
    candidates.append((step.get("tool_info") or {}).get("args"))
    # Legado Claude Code: bloco tool_use dentro de message.content.
    for block in (raw.get("message") or {}).get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            candidates.append(block.get("input"))
    for args in candidates:
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                continue
        if not isinstance(args, dict):
            continue
        for key in _TOOL_DETAIL_KEYS:
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:200]
    return None


def _frame(kind: str, payload: dict) -> str:
    return f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _event_payload(event: AgentEvent) -> dict:
    payload = {
        "type": event.type.value,
        "text": event.text,
        "timestamp": event.timestamp.isoformat(),
    }
    if event.type == AgentEventType.TOOL_USE:
        payload["detail"] = _tool_detail(event.raw)
    return payload


@router.get("/{task_id}/stream")
async def stream_task(task_id: str, request: Request):
    """Server-sent events with what the task's agent is doing right now.

    The first frame, STATE, says whether this process is running the task at
    all: after a restart the tracker can still say RUNNING with nobody behind it.
    """
    activity = request.app.state.orchestrator.activity
    run = activity.get(task_id)

    async def publisher():
        yield _frame("STATE", {
            "active": run is not None and not run.done,
            "started_at": run.started_at.isoformat() if run else None,
            "last_event_at": run.last_event_at.isoformat() if run and run.last_event_at else None,
        })
        if run is not None:
            async for event in activity.subscribe(task_id):
                yield _frame(event.type.value, _event_payload(event))
        yield _frame("CLOSE", {})

    return StreamingResponse(
        publisher(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{task_id}/clarification")
async def get_clarification(task_id: str, request: Request):
    tracker = request.app.state.tracker
    clar = await tracker.get_pending_clarification(task_id)
    if not clar:
        return {"status": "none"}
    return clar


@router.post("/{task_id}/clarification")
async def reply_clarification(task_id: str, req: ClarificationReplyRequest, request: Request):
    tracker = request.app.state.tracker
    orchestrator = request.app.state.orchestrator
    clar = await tracker.get_pending_clarification(task_id)
    if not clar:
        raise HTTPException(status_code=404, detail="No pending clarification for this task")

    updated_task = await orchestrator.reply_clarification(clar.id, req.answer)
    return updated_task


@router.post("/{task_id}/merge")
async def merge_task(task_id: str, request: Request):
    orchestrator = request.app.state.orchestrator
    try:
        updated_task = await orchestrator.merge_task(task_id)
        return updated_task
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{task_id}/diff")
async def get_task_diff(task_id: str, request: Request):
    tracker = request.app.state.tracker
    git = request.app.state.git
    vcs = getattr(request.app.state, "vcs", None)

    task = await tracker.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    project = await tracker.get_project(task.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    diff_content = await git.get_diff(project.repo_path, base_branch=project.default_branch)

    gitea_url = None
    if task.assigned_branch and project.repo_url:
        # repo_url já aponta para o dono certo (usuário ou conta de serviço).
        gitea_url = f"{project.repo_url}/compare/{project.default_branch}...{task.assigned_branch}"
    elif vcs and task.assigned_branch:
        gitea_url = vcs.get_diff_url(
            repo_name=project.name,
            branch_name=task.assigned_branch,
            base_branch=project.default_branch,
        )

    return {
        "task_id": task_id,
        "branch": task.assigned_branch or f"feature/{task.id}",
        "base_branch": project.default_branch,
        "diff": diff_content,
        "gitea_url": gitea_url,
    }

