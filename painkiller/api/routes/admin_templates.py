"""Admin Project Templates routes with CRUD, file uploads and Coolify compatibility."""

import os
import shutil
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from painkiller.api.security import require_admin, current_user
from painkiller.core.domain.models import ProjectTemplate, ProjectType, is_coolify_compatible, User


router = APIRouter(prefix="/api/admin/templates", tags=["admin-templates"])
public_router = APIRouter(prefix="/api/templates", tags=["templates"])


def _get_storage_dir() -> str:
    return os.environ.get("PAINKILLER_STORAGE_DIR") or os.path.join(os.getcwd(), "storage")


def _template_storage_dir(template_id: str) -> str:
    path = os.path.join(_get_storage_dir(), "templates", template_id)
    os.makedirs(path, exist_ok=True)
    return path


class CreateTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = ""
    project_type: ProjectType = ProjectType.WEB_FULLSTACK
    coolify_compatible: Optional[bool] = None
    prompt: Optional[str] = ""
    is_active: Optional[bool] = True


class UpdateTemplateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    project_type: Optional[ProjectType] = None
    coolify_compatible: Optional[bool] = None
    prompt: Optional[str] = None
    is_active: Optional[bool] = None


# ---- Admin Endpoints ----

@router.get("", dependencies=[Depends(require_admin)])
async def list_admin_templates(request: Request):
    tracker = request.app.state.tracker
    templates = await tracker.list_project_templates(active_only=False)
    return [t.model_dump(mode="json") for t in templates]


@router.post("", dependencies=[Depends(require_admin)])
async def create_admin_template(req: CreateTemplateRequest, request: Request):
    tracker = request.app.state.tracker

    coolify_compatible = (
        req.coolify_compatible
        if req.coolify_compatible is not None
        else is_coolify_compatible(req.project_type)
    )

    template = await tracker.create_project_template(
        name=req.name.strip(),
        project_type=req.project_type,
        description=(req.description or "").strip(),
        coolify_compatible=coolify_compatible,
        prompt=(req.prompt or "").strip(),
        is_active=True if req.is_active is None else req.is_active,
    )
    return template.model_dump(mode="json")


@router.get("/{template_id}", dependencies=[Depends(require_admin)])
async def get_admin_template(template_id: str, request: Request):
    tracker = request.app.state.tracker
    template = await tracker.get_project_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    return template.model_dump(mode="json")


@router.put("/{template_id}", dependencies=[Depends(require_admin)])
async def update_admin_template(template_id: str, req: UpdateTemplateRequest, request: Request):
    tracker = request.app.state.tracker
    existing = await tracker.get_project_template(template_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Template não encontrado")

    coolify_comp = req.coolify_compatible
    if coolify_comp is None and req.project_type is not None:
        # Se alterou o tipo e não especificou compatibilidade, recalcula
        coolify_comp = is_coolify_compatible(req.project_type)

    updated = await tracker.update_project_template(
        template_id=template_id,
        name=req.name.strip() if req.name is not None else None,
        description=req.description.strip() if req.description is not None else None,
        project_type=req.project_type,
        coolify_compatible=coolify_comp,
        prompt=req.prompt if req.prompt is not None else None,
        is_active=req.is_active,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    return updated.model_dump(mode="json")


@router.delete("/{template_id}", dependencies=[Depends(require_admin)])
async def delete_admin_template(template_id: str, request: Request):
    tracker = request.app.state.tracker
    template = await tracker.get_project_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template não encontrado")

    # Remove arquivos associados do disco
    storage_dir = os.path.join(_get_storage_dir(), "templates", template_id)
    if os.path.exists(storage_dir):
        try:
            shutil.rmtree(storage_dir, ignore_errors=True)
        except Exception:
            pass

    deleted = await tracker.delete_project_template(template_id)
    return {"deleted": deleted}


@router.post("/{template_id}/skill", dependencies=[Depends(require_admin)])
async def upload_template_skill(template_id: str, request: Request, file: UploadFile = File(...)):
    tracker = request.app.state.tracker
    template = await tracker.get_project_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template não encontrado")

    original_filename = file.filename or "skill.md"
    ext = Path(original_filename).suffix.lower()
    if ext not in [".zip", ".md"]:
        raise HTTPException(status_code=400, detail="A skill deve ser um arquivo .zip ou .md")

    storage_dir = _template_storage_dir(template_id)
    dest_path = os.path.join(storage_dir, f"skill{ext}")

    # Remove skill antiga se existir
    if template.skill_path and os.path.exists(template.skill_path) and template.skill_path != dest_path:
        try:
            os.remove(template.skill_path)
        except OSError:
            pass

    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    updated = await tracker.update_project_template(
        template_id=template_id,
        skill_path=dest_path,
        skill_filename=original_filename,
    )
    return updated.model_dump(mode="json")


@router.delete("/{template_id}/skill", dependencies=[Depends(require_admin)])
async def delete_template_skill(template_id: str, request: Request):
    tracker = request.app.state.tracker
    template = await tracker.get_project_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template não encontrado")

    if template.skill_path and os.path.exists(template.skill_path):
        try:
            os.remove(template.skill_path)
        except OSError:
            pass

    updated = await tracker.update_project_template(
        template_id=template_id,
        skill_path="",
        skill_filename="",
    )
    return updated.model_dump(mode="json")


@router.get("/{template_id}/skill/download", dependencies=[Depends(current_user)])
async def download_template_skill(template_id: str, request: Request):
    tracker = request.app.state.tracker
    template = await tracker.get_project_template(template_id)
    if not template or not template.skill_path or not os.path.exists(template.skill_path):
        raise HTTPException(status_code=404, detail="Arquivo de skill não encontrado")

    filename = template.skill_filename or os.path.basename(template.skill_path)
    return FileResponse(
        template.skill_path,
        filename=filename,
        media_type="application/octet-stream",
    )


@router.post("/{template_id}/scaffold", dependencies=[Depends(require_admin)])
async def upload_template_scaffold(template_id: str, request: Request, file: UploadFile = File(...)):
    tracker = request.app.state.tracker
    template = await tracker.get_project_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template não encontrado")

    original_filename = file.filename or "scaffold.zip"
    ext = Path(original_filename).suffix.lower()
    if ext != ".zip":
        raise HTTPException(status_code=400, detail="O arcabouço da aplicação deve ser um arquivo .zip")

    storage_dir = _template_storage_dir(template_id)
    dest_path = os.path.join(storage_dir, "scaffold.zip")

    if template.scaffold_path and os.path.exists(template.scaffold_path) and template.scaffold_path != dest_path:
        try:
            os.remove(template.scaffold_path)
        except OSError:
            pass

    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    updated = await tracker.update_project_template(
        template_id=template_id,
        scaffold_path=dest_path,
        scaffold_filename=original_filename,
    )
    return updated.model_dump(mode="json")


@router.delete("/{template_id}/scaffold", dependencies=[Depends(require_admin)])
async def delete_template_scaffold(template_id: str, request: Request):
    tracker = request.app.state.tracker
    template = await tracker.get_project_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template não encontrado")

    if template.scaffold_path and os.path.exists(template.scaffold_path):
        try:
            os.remove(template.scaffold_path)
        except OSError:
            pass

    updated = await tracker.update_project_template(
        template_id=template_id,
        scaffold_path="",
        scaffold_filename="",
    )
    return updated.model_dump(mode="json")


@router.get("/{template_id}/scaffold/download", dependencies=[Depends(current_user)])
async def download_template_scaffold(template_id: str, request: Request):
    tracker = request.app.state.tracker
    template = await tracker.get_project_template(template_id)
    if not template or not template.scaffold_path or not os.path.exists(template.scaffold_path):
        raise HTTPException(status_code=404, detail="Arquivo de arcabouço não encontrado")

    filename = template.scaffold_filename or os.path.basename(template.scaffold_path)
    return FileResponse(
        template.scaffold_path,
        filename=filename,
        media_type="application/zip",
    )


# ---- Public / General Endpoints (Para criação de projetos) ----

@public_router.get("", dependencies=[Depends(current_user)])
async def list_active_templates(request: Request):
    tracker = request.app.state.tracker
    templates = await tracker.list_project_templates(active_only=True)
    return [t.model_dump(mode="json") for t in templates]


@public_router.get("/{template_id}", dependencies=[Depends(current_user)])
async def get_active_template(template_id: str, request: Request):
    tracker = request.app.state.tracker
    template = await tracker.get_project_template(template_id)
    if not template or not template.is_active:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    return template.model_dump(mode="json")
