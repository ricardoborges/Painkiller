"""Interrogation wizard routes."""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from painkiller.api.security import visible_project

router = APIRouter(prefix="/api/interrogation", tags=["interrogation"])


class StartInterrogationRequest(BaseModel):
    project_id: str
    goal: str


class ReplyInterrogationRequest(BaseModel):
    session_id: str
    answer: str


class CommitBacklogRequest(BaseModel):
    session_id: str


async def _authorize_session(request: Request, session_id: str) -> None:
    session = request.app.state.wizard.sessions.get(session_id)
    if session is not None:
        await visible_project(request, session.project_id)


@router.post("/start")
async def start_session(req: StartInterrogationRequest, request: Request):
    wizard = request.app.state.wizard
    await visible_project(request, req.project_id)
    session = await wizard.start_session(project_id=req.project_id, initial_goal=req.goal)
    return {
        "session_id": session.session_id,
        "question": session.history[-1]["content"],
        "history": session.history,
    }


@router.post("/reply")
async def reply_session(req: ReplyInterrogationRequest, request: Request):
    wizard = request.app.state.wizard
    await _authorize_session(request, req.session_id)
    try:
        reply, is_complete = await wizard.reply(req.session_id, req.answer)
        return {
            "reply": reply,
            "is_complete": is_complete,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/commit")
async def commit_backlog(req: CommitBacklogRequest, request: Request):
    wizard = request.app.state.wizard
    await _authorize_session(request, req.session_id)
    try:
        tasks = await wizard.commit_backlog(req.session_id)
        return tasks
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
