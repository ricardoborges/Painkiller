"""Run queue routes: the server-side "Executar Todas" of a project."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from painkiller.api.security import require_project
from painkiller.core.i18n import translate
from painkiller.engine.orchestrator import ProjectBusyError
from painkiller.engine.run_queue import QueueBusyError, QueueSessionError, SessionClosedError

router = APIRouter(
    prefix="/api/projects/{project_id}/queue",
    tags=["queue"],
    dependencies=[Depends(require_project)],
)


class StartQueueRequest(BaseModel):
    session_id: Optional[str] = None


def _view(state: dict) -> dict:
    # O detalhe é a mensagem pt-BR do engine; sai no idioma de quem lê.
    return {**state, "detail": translate(state.get("detail") or "")}


@router.get("")
async def get_queue(project_id: str, request: Request):
    return _view(request.app.state.run_queue.state(project_id))


@router.post("")
async def start_queue(project_id: str, body: StartQueueRequest, request: Request):
    """Run the session's pending tasks in order, in the background; returns at once."""
    project = await request.app.state.tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    if not project.api_key:
        raise HTTPException(
            status_code=400,
            detail="Este projeto não tem chave de API cadastrada. Abra Editar projeto e informe a chave "
            "do provedor do harness antes de despachar tarefas.",
        )
    try:
        return _view(await request.app.state.run_queue.start(project, body.session_id))
    except (QueueBusyError, ProjectBusyError, SessionClosedError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    except QueueSessionError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("")
async def pause_queue(project_id: str, request: Request):
    """Stop the queue after the task that is running now."""
    return _view(request.app.state.run_queue.pause(project_id))
