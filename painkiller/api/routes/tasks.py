"""Task routes."""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


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
