"""Interactive initial-analysis routes (Claude Code + superpowers, streamed)."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from painkiller.api.security import require_analysis, visible_project

router = APIRouter(prefix="/api", tags=["analysis"])


class MessageRequest(BaseModel):
    answer: str


def _session_payload(session) -> dict:
    return {
        "session_id": session.id,
        "project_id": session.project_id,
        "status": session.status.value,
        "container_name": session.container_name,
        "claude_session_id": getattr(session, "claude_session_id", None),
        "exit_code": session.exit_code,
        "error": session.error,
        "spec_path": session.spec_path,
    }


async def _require_iteration(request: Request, project_id: str, iteration_session_id: str):
    iter_sess = await request.app.state.tracker.get_session(iteration_session_id)
    if not iter_sess or iter_sess.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    return iter_sess


@router.get("/projects/{project_id}/analysis/current")
async def get_current_analysis(
    project_id: str, request: Request, iteration_session_id: Optional[str] = None
):
    """Retrieve the current active analysis session for a project, if any.

    With `iteration_session_id`, only an analysis bound to that iteration session counts.
    """
    analysis = request.app.state.analysis

    await visible_project(request, project_id)

    if iteration_session_id:
        await _require_iteration(request, project_id, iteration_session_id)
        session = await analysis.get_active_for(project_id, iteration_session_id)
    else:
        session = await analysis.get_active(project_id)
    if not session:
        return {"session": None}
    return {"session": _session_payload(session)}


@router.post("/projects/{project_id}/analysis")
async def start_analysis(
    project_id: str,
    request: Request,
    force_new: bool = False,
    iteration_session_id: Optional[str] = None,
):
    """Boot or resume the agent container and return immediately — the UI then opens the stream."""
    analysis = request.app.state.analysis

    project = await visible_project(request, project_id)
    if iteration_session_id:
        await _require_iteration(request, project_id, iteration_session_id)

    try:
        session = await analysis.start(
            project, force_new=force_new, iteration_session_id=iteration_session_id
        )
    except RuntimeError as e:
        # Credencial ausente ou imagem não construída: a mensagem já é pt-BR.
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha ao iniciar o agente: {e}")

    return _session_payload(session)


@router.get("/analysis/{session_id}", dependencies=[Depends(require_analysis)])
async def get_analysis(session_id: str, request: Request):
    analysis = request.app.state.analysis
    try:
        return _session_payload(analysis.get(session_id))
    except ValueError:
        try:
            return _session_payload(await analysis.get_or_restore(session_id))
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))


@router.get("/analysis/{session_id}/stream", dependencies=[Depends(require_analysis)])
async def stream_analysis(session_id: str, request: Request):
    """Server-sent events carrying the agent's output as it is produced."""
    analysis = request.app.state.analysis
    try:
        analysis.get(session_id)
    except ValueError:
        try:
            await analysis.get_or_restore(session_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    async def publisher():
        async for event in analysis.subscribe(session_id):
            payload = {
                "type": event.type.value,
                "text": event.text,
                "timestamp": event.timestamp.isoformat(),
            }
            yield f"event: {event.type.value}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        yield "event: CLOSE\ndata: {}\n\n"

    return StreamingResponse(
        publisher(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Impede que um proxy reverso segure o corpo e mate o streaming.
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/analysis/{session_id}/message", dependencies=[Depends(require_analysis)])
async def send_message(session_id: str, req: MessageRequest, request: Request):
    try:
        session = await request.app.state.analysis.send(session_id, req.answer)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _session_payload(session)


@router.post("/analysis/{session_id}/finish", dependencies=[Depends(require_analysis)])
async def finish_analysis(session_id: str, request: Request):
    """Close the agent's input so it finishes the turn and exits cleanly."""
    try:
        session = await request.app.state.analysis.finish(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _session_payload(session)


@router.post("/analysis/{session_id}/commit", dependencies=[Depends(require_analysis)])
async def commit_analysis_backlog(
    session_id: str, request: Request, iteration_session_id: Optional[str] = None
):
    analysis = request.app.state.analysis
    if iteration_session_id:
        run = analysis.runs.get(session_id)
        if run:
            await _require_iteration(request, run.session.project_id, iteration_session_id)
    try:
        return await analysis.commit_backlog(session_id, iteration_session_id=iteration_session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Backlog inválido: {e}")


@router.delete("/analysis/{session_id}", dependencies=[Depends(require_analysis)])
async def stop_analysis(session_id: str, request: Request):
    await request.app.state.analysis.stop(session_id)
    return {"status": "stopped"}
