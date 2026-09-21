"""Project routes with full CRUD, contextualization fields, and attachment upload."""

import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from painkiller.core.attachment_reader import extract_attachment_text

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str
    repo_path: Optional[str] = ""
    description: Optional[str] = ""
    purpose: Optional[str] = ""
    solution_description: Optional[str] = ""
    default_branch: Optional[str] = "main"


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    purpose: Optional[str] = None
    solution_description: Optional[str] = None


class CreateTaskRequest(BaseModel):
    title: str
    description: str
    target_files: Optional[list[str]] = None
    acceptance_criteria: Optional[list[str]] = None
    dependencies: Optional[list[str]] = None


@router.get("")
async def list_projects(request: Request):
    tracker = request.app.state.tracker
    return await tracker.list_projects()


@router.post("")
async def create_project(req: CreateProjectRequest, request: Request):
    tracker = request.app.state.tracker
    git = request.app.state.git
    vcs = getattr(request.app.state, "vcs", None)

    # Default repo path inside storage if not provided
    proj_id_temp = f"proj-{uuid.uuid4().hex[:8]}"
    base_repo_path = req.repo_path or os.path.join(os.getcwd(), "storage", "projects", proj_id_temp, "repo")
    os.makedirs(base_repo_path, exist_ok=True)

    default_branch = req.default_branch or "main"
    await git.init_repo(base_repo_path, default_branch=default_branch, initial_commit=True)

    repo_url = None
    if vcs:
        try:
            repo_info = await vcs.create_repository(name=req.name, description=req.description or "")
            await git.set_remote(base_repo_path, repo_info["clone_url_internal"], remote_name="origin")
            await git.push(base_repo_path, default_branch, remote_name="origin", set_upstream=True)
            repo_url = repo_info["web_url_external"]
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Could not link Gitea repo for {req.name}: {e}")

    project = await tracker.create_project(
        name=req.name,
        repo_path=base_repo_path,
        description=req.description or "",
        purpose=req.purpose or "",
        solution_description=req.solution_description or "",
        default_branch=default_branch,
        repo_url=repo_url,
    )
    return project


@router.get("/{project_id}")
async def get_project(project_id: str, request: Request):
    tracker = request.app.state.tracker
    project = await tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    return project


@router.put("/{project_id}")
async def update_project(project_id: str, req: UpdateProjectRequest, request: Request):
    tracker = request.app.state.tracker
    try:
        updated = await tracker.update_project(
            project_id=project_id,
            name=req.name,
            description=req.description,
            purpose=req.purpose,
            solution_description=req.solution_description,
        )
        return updated
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{project_id}")
async def delete_project(project_id: str, request: Request):
    tracker = request.app.state.tracker
    await tracker.delete_project(project_id)
    return {"status": "deleted", "project_id": project_id}


@router.post("/{project_id}/attachments")
async def upload_attachment(project_id: str, file: UploadFile = File(...), request: Request = None):
    tracker = request.app.state.tracker
    project = await tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    storage_dir = os.path.join(os.getcwd(), "storage", "projects", project_id, "attachments")
    os.makedirs(storage_dir, exist_ok=True)

    filename = f"{uuid.uuid4().hex[:6]}_{file.filename}"
    file_path = os.path.join(storage_dir, filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    current_attachments = list(project.attachments)
    current_attachments.append(file_path)

    updated_project = await tracker.update_project(
        project_id=project_id,
        attachments=current_attachments,
    )
    return {
        "status": "uploaded",
        "file_name": file.filename,
        "file_path": file_path,
        "project": updated_project,
    }


@router.post("/{project_id}/start-interrogation")
async def start_project_interrogation(project_id: str, request: Request):
    tracker = request.app.state.tracker
    wizard = request.app.state.wizard

    project = await tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    # Compile contextualization prompt from structured fields + attachments
    context_parts = [
        f"Nome do Projeto: {project.name}",
        f"Descrição Geral: {project.description}",
        f"Propósito de Negócio: {project.purpose}",
        f"Descrição da Solução: {project.solution_description}",
    ]

    if project.attachments:
        context_parts.append("\n=== DOCUMENTOS DE CONTEXTO ANEXADOS ===")
        for att_path in project.attachments:
            extracted_text = extract_attachment_text(att_path)
            context_parts.append(extracted_text)

    initial_goal = "\n\n".join(context_parts)

    try:
        session = await wizard.start_session(project_id=project.id, initial_goal=initial_goal)
        return {
            "session_id": session.session_id,
            "project_id": project.id,
            "question": session.history[-1]["content"],
            "history": session.history,
        }
    except Exception as e:
        # Graceful fallback if LLM API key fails or network error
        return {
            "session_id": f"session-{uuid.uuid4().hex[:8]}",
            "project_id": project.id,
            "question": f"Contextualização carregada com sucesso para '{project.name}'.\n\n(Aviso de LLM: {e})\n\nPor favor, informe quais endpoints ou requisitos iniciais devemos priorizar?",
            "history": [{"role": "system", "content": "Contextualização carregada."}],
        }


@router.post("/{project_id}/tasks")
async def create_task(project_id: str, req: CreateTaskRequest, request: Request):
    tracker = request.app.state.tracker
    task = await tracker.create_task(
        project_id=project_id,
        title=req.title,
        description=req.description,
        target_files=req.target_files,
        acceptance_criteria=req.acceptance_criteria,
        dependencies=req.dependencies,
    )
    return task


@router.get("/{project_id}/tasks")
async def list_tasks(project_id: str, request: Request):
    tracker = request.app.state.tracker
    tasks = await tracker.list_tasks(project_id=project_id)
    return tasks


@router.get("/{project_id}/docs")
async def list_project_docs(project_id: str, request: Request):
    """List superpowers specifications, implementation plans, and backlog files."""
    tracker = request.app.state.tracker
    project = await tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

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
                results.append({
                    "path": rel_path,
                    "filename": file_path.name,
                    "category": category,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
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
        })

    # Sort most recent first
    results.sort(key=lambda x: x["modified_at"], reverse=True)
    return results


@router.get("/{project_id}/docs/content")
async def get_project_doc_content(project_id: str, path: str, request: Request):
    """Retrieve the text content of a specific superpowers document."""
    tracker = request.app.state.tracker
    project = await tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    repo_dir = Path(project.repo_path).resolve()
    target = (repo_dir / path).resolve()

    # Prevent directory traversal
    if not target.is_relative_to(repo_dir):
        raise HTTPException(status_code=403, detail="Acesso restrito ao repositório do projeto")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="Documento não encontrado")

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao ler arquivo: {e}")

    stat = target.stat()
    return {
        "path": path,
        "filename": target.name,
        "content": content,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }

