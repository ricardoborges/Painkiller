"""Admin routes for the built-in project templates (native Kotlin, Capacitor + React).

Os templates são fixos, semeados no startup (``ensure_builtin_templates``): o
admin não cria nem apaga templates, só configura os que existem e pode trocar o
arcabouço embutido de cada um por um .zip próprio. Sem .zip, vale o embutido.
"""

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from painkiller.api.security import require_admin, current_user
from painkiller.core.templates import builtin_template, has_uploaded_scaffold
from painkiller.core.domain.models import ProjectTemplate
from painkiller.core.scaffold import zip_scaffold_dir


router = APIRouter(prefix="/api/admin/templates", tags=["admin-templates"])
public_router = APIRouter(prefix="/api/templates", tags=["templates"])


def _get_storage_dir() -> str:
    return os.environ.get("PAINKILLER_STORAGE_DIR") or os.path.join(os.getcwd(), "storage")


def _template_storage_dir(template_id: str) -> str:
    path = os.path.join(_get_storage_dir(), "templates", template_id)
    os.makedirs(path, exist_ok=True)
    return path


def _format_template(template: ProjectTemplate) -> dict:
    data = template.model_dump(mode="json")
    # Sem .zip do admin, o projeto nasce do arcabouço embutido.
    data["bundled_scaffold"] = not has_uploaded_scaffold(template)
    return data


async def _require_template(request: Request, template_id: str) -> ProjectTemplate:
    template = await request.app.state.tracker.get_project_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    return template


class UpdateTemplateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    prompt: Optional[str] = None


# ---- Admin Endpoints ----

@router.get("", dependencies=[Depends(require_admin)])
async def list_admin_templates(request: Request):
    templates = await request.app.state.tracker.list_project_templates(active_only=False)
    return [_format_template(t) for t in templates]


@router.get("/{template_id}", dependencies=[Depends(require_admin)])
async def get_admin_template(template_id: str, request: Request):
    return _format_template(await _require_template(request, template_id))


@router.put("/{template_id}", dependencies=[Depends(require_admin)])
async def update_admin_template(template_id: str, req: UpdateTemplateRequest, request: Request):
    await _require_template(request, template_id)
    if req.name is not None and not req.name.strip():
        raise HTTPException(status_code=400, detail="Informe o nome do template")
    updated = await request.app.state.tracker.update_project_template(
        template_id=template_id,
        name=req.name.strip() if req.name is not None else None,
        description=req.description,
        prompt=req.prompt,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    return _format_template(updated)


@router.post("/{template_id}/skill", dependencies=[Depends(require_admin)])
async def upload_template_skill(template_id: str, request: Request, file: UploadFile = File(...)):
    tracker = request.app.state.tracker
    template = await _require_template(request, template_id)

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
    return _format_template(updated)


@router.delete("/{template_id}/skill", dependencies=[Depends(require_admin)])
async def delete_template_skill(template_id: str, request: Request):
    tracker = request.app.state.tracker
    template = await _require_template(request, template_id)

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
    return _format_template(updated)


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
    template = await _require_template(request, template_id)

    original_filename = file.filename or "scaffold.zip"
    ext = Path(original_filename).suffix.lower()
    if ext != ".zip":
        raise HTTPException(status_code=400, detail="O arcabouço da aplicação deve ser um arquivo .zip")

    storage_dir = _template_storage_dir(template_id)
    dest_path = os.path.join(storage_dir, "scaffold.zip")
    # Grava ao lado e só troca se for um zip de verdade: um upload ruim não
    # pode derrubar o arcabouço que já funcionava.
    staging = dest_path + ".upload"
    with open(staging, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    if not zipfile.is_zipfile(staging):
        os.remove(staging)
        raise HTTPException(status_code=400, detail="O arcabouço da aplicação deve ser um arquivo .zip")

    if template.scaffold_path and os.path.exists(template.scaffold_path) and template.scaffold_path != dest_path:
        try:
            os.remove(template.scaffold_path)
        except OSError:
            pass
    os.replace(staging, dest_path)

    updated = await tracker.update_project_template(
        template_id=template_id,
        scaffold_path=dest_path,
        scaffold_filename=original_filename,
    )
    return _format_template(updated)


@router.delete("/{template_id}/scaffold", dependencies=[Depends(require_admin)])
async def delete_template_scaffold(template_id: str, request: Request):
    """Drop the admin's .zip: new projects go back to the bundled scaffold."""
    tracker = request.app.state.tracker
    template = await _require_template(request, template_id)

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
    return _format_template(updated)


@router.get("/{template_id}/scaffold/download", dependencies=[Depends(current_user)])
async def download_template_scaffold(template_id: str, request: Request, background: BackgroundTasks):
    tracker = request.app.state.tracker
    template = await tracker.get_project_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Arquivo de arcabouço não encontrado")

    if has_uploaded_scaffold(template):
        filename = template.scaffold_filename or os.path.basename(template.scaffold_path)
        return FileResponse(template.scaffold_path, filename=filename, media_type="application/zip")

    # O embutido sai empacotado na hora: é o ponto de partida para o admin adaptar.
    fd, zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    bundled = builtin_template(template.id)
    zip_scaffold_dir(bundled.scaffold_dir, zip_path)
    background.add_task(os.remove, zip_path)
    return FileResponse(zip_path, filename=bundled.scaffold_filename, media_type="application/zip")


# ---- Public / General Endpoints (Para criação de projetos) ----

@public_router.get("", dependencies=[Depends(current_user)])
async def list_active_templates(request: Request):
    templates = await request.app.state.tracker.list_project_templates(active_only=True)
    return [_format_template(t) for t in templates]


@public_router.get("/{template_id}", dependencies=[Depends(current_user)])
async def get_active_template(template_id: str, request: Request):
    template = await request.app.state.tracker.get_project_template(template_id)
    if not template or not template.is_active:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    return _format_template(template)
