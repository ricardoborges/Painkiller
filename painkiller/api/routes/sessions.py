"""API routes for managing iterative agile sessions, their tasks and artifacts."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from painkiller.core.domain.models import SessionStatus, TaskStatus

router = APIRouter(prefix="/api/projects/{project_id}/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    title: Optional[str] = None


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[SessionStatus] = None
    spec_path: Optional[str] = None
    analysis_session_id: Optional[str] = None


class MigrateTasksRequest(BaseModel):
    task_ids: list[str]


@router.get("")
async def list_sessions(project_id: str, request: Request):
    """List all agile iteration sessions for a project.
    
    Creates Session 1 automatically if no sessions exist.
    """
    tracker = request.app.state.tracker
    project = await tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    sessions = await tracker.list_sessions(project_id)
    if not sessions:
        # Auto-criação da Sessão 1 ao abrir o projeto
        initial = await tracker.ensure_initial_session(project_id)
        sessions = [initial]

    return sessions


@router.post("")
async def create_session(project_id: str, request: Request, req: Optional[CreateSessionRequest] = None):
    """Create the next incremental agile iteration session for the project."""
    tracker = request.app.state.tracker
    project = await tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    title = req.title if req else None
    session = await tracker.create_session(project_id=project_id, title=title)
    return session


@router.get("/{session_id}")
async def get_session(project_id: str, session_id: str, request: Request):
    """Get details of a specific iteration session."""
    tracker = request.app.state.tracker
    session = await tracker.get_session(session_id)
    if not session or session.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    return session


@router.patch("/{session_id}")
async def update_session(project_id: str, session_id: str, req: UpdateSessionRequest, request: Request):
    """Update title, status or linked spec of an iteration session."""
    tracker = request.app.state.tracker
    session = await tracker.get_session(session_id)
    if not session or session.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")

    if req.title is not None:
        session.title = req.title
    if req.status is not None:
        session.status = req.status
    if req.spec_path is not None:
        session.spec_path = req.spec_path
    if req.analysis_session_id is not None:
        session.analysis_session_id = req.analysis_session_id

    session.updated_at = datetime.now(timezone.utc)
    updated = await tracker.update_session(session)
    return updated


@router.get("/{session_id}/tasks")
async def list_session_tasks(
    project_id: str,
    session_id: str,
    request: Request,
    status: Optional[TaskStatus] = None,
):
    """List tasks assigned to this iteration session."""
    tracker = request.app.state.tracker
    session = await tracker.get_session(session_id)
    if not session or session.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")

    tasks = await tracker.list_tasks(project_id=project_id, status=status, session_id=session_id)
    return tasks


@router.get("/{session_id}/artifacts")
async def list_session_artifacts(project_id: str, session_id: str, request: Request):
    """List superpowers artifacts (specs, plans, backlog) linked to this session."""
    tracker = request.app.state.tracker
    project = await tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    session = await tracker.get_session(session_id)
    if not session or session.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")

    repo_dir = Path(project.repo_path).resolve()
    if not repo_dir.exists():
        return []

    results = []
    # 1. Look for docs in docs/ (including specs and plans)
    docs_dir = repo_dir / "docs"
    if docs_dir.exists():
        for file_path in docs_dir.rglob("*.md"):
            if file_path.is_file():
                rel_path = file_path.relative_to(repo_dir).as_posix()
                category = "doc"
                if "specs" in rel_path:
                    category = "spec"
                elif "plans" in rel_path:
                    category = "plan"

                stat = file_path.stat()
                # Se a sessão tiver um spec específico apontado, dar prioridade
                is_current_session_spec = (session.spec_path and rel_path == session.spec_path)

                results.append({
                    "path": rel_path,
                    "filename": file_path.name,
                    "category": category,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    "is_session_spec": bool(is_current_session_spec),
                })

    # 2. Look for .painkiller/backlog.json
    backlog_file = repo_dir / ".painkiller" / "backlog.json"
    if backlog_file.is_file():
        stat = backlog_file.stat()
        results.append({
            "path": ".painkiller/backlog.json",
            "filename": "backlog.json",
            "category": "backlog",
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "is_session_spec": False,
        })

    return results


@router.post("/{session_id}/migrate-tasks")
async def migrate_tasks_to_session(project_id: str, session_id: str, req: MigrateTasksRequest, request: Request):
    """Migrate pending or incomplete tasks from previous sessions into this session."""
    tracker = request.app.state.tracker
    session = await tracker.get_session(session_id)
    if not session or session.project_id != project_id:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")

    migrated = await tracker.migrate_tasks_to_session(req.task_ids, target_session_id=session_id)
    return migrated
