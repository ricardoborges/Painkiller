"""Project routes with full CRUD, contextualization fields, and attachment upload."""

import os
import shutil
import uuid
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
    # Default repo path inside storage if not provided
    proj_id_temp = f"proj-{uuid.uuid4().hex[:8]}"
    base_repo_path = req.repo_path or os.path.join(os.getcwd(), "storage", "projects", proj_id_temp, "repo")
    os.makedirs(base_repo_path, exist_ok=True)

    project = await tracker.create_project(
        name=req.name,
        repo_path=base_repo_path,
        description=req.description or "",
        purpose=req.purpose or "",
        solution_description=req.solution_description or "",
        default_branch=req.default_branch or "main",
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
