"""Project routes with full CRUD, contextualization fields, and attachment upload."""

import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel

from painkiller.api.routes.auth import ensure_gitea_account
from painkiller.api.security import current_user, require_project, visible_project
from painkiller.core.attachment_reader import extract_attachment_text
from painkiller.core.domain.models import EFFORT_HARNESSES, EFFORT_LEVELS, User, harness_effort, key_provider
from painkiller.core.naming import compose_project_identity

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str
    repo_path: Optional[str] = ""
    description: Optional[str] = ""
    purpose: Optional[str] = ""
    solution_description: Optional[str] = ""
    default_branch: Optional[str] = "main"
    harness: Optional[str] = "agy_superpowers"
    api_key: Optional[str] = None
    model: Optional[str] = None
    effort: Optional[str] = None


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    purpose: Optional[str] = None
    solution_description: Optional[str] = None
    harness: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    effort: Optional[str] = None


class ValidateKeyRequest(BaseModel):
    harness: Optional[str] = "agy_superpowers"
    api_key: str = ""


#: Nome do provedor como o analista o conhece, para as mensagens de erro.
PROVIDER_LABELS = {"gemini": "Google Gemini", "deepseek": "DeepSeek"}


class CreateTaskRequest(BaseModel):
    title: str
    description: str
    target_files: Optional[list[str]] = None
    acceptance_criteria: Optional[list[str]] = None
    dependencies: Optional[list[str]] = None
    session_id: Optional[str] = None


def _checked_effort(harness: Optional[str], effort: Optional[str]) -> Optional[str]:
    """The effort to store: validated when the harness has the setting, dropped otherwise."""
    if (getattr(harness, "value", harness) or "agy_superpowers") not in EFFORT_HARNESSES:
        return None
    if effort and effort not in EFFORT_LEVELS:
        raise HTTPException(status_code=400, detail=f"Esforço inválido. Use um de: {', '.join(EFFORT_LEVELS)}.")
    return harness_effort(harness, effort)


def _get_storage_dir() -> str:
    return os.environ.get("PAINKILLER_STORAGE_DIR") or os.path.join(os.getcwd(), "storage")


def _format_project(p) -> dict:
    data = p.model_dump(mode="json")
    data.pop("api_key", None)
    data["has_api_key"] = bool(p.api_key)
    data["masked_api_key"] = p.masked_api_key
    return data


@router.get("")
async def list_projects(request: Request, user: User = Depends(current_user)):
    tracker = request.app.state.tracker
    # O admin break-glass vê tudo; os demais, só os próprios projetos.
    projects = await tracker.list_projects(owner_id=None if user.is_admin else user.id)
    return [_format_project(p) for p in projects]


@router.post("/validate-key")
async def validate_project_key(req: ValidateKeyRequest, request: Request):
    """Ask the harness' provider whether the key works, before saving the project."""
    return await request.app.state.key_validator(key_provider(req.harness), req.api_key)


@router.post("")
async def create_project(req: CreateProjectRequest, request: Request, user: User = Depends(current_user)):
    tracker = request.app.state.tracker
    git = request.app.state.git
    vcs = getattr(request.app.state, "vcs", None)

    # Caminho arbitrário no servidor só para o admin: senão um usuário poderia
    # apontar para o repositório de outro e ler seus artefatos.
    if req.repo_path and not user.is_admin:
        raise HTTPException(status_code=403, detail="Só o administrador pode escolher o caminho do repositório")

    # Não há chave global de servidor: cada projeto paga o próprio consumo.
    if not (req.api_key or "").strip():
        provider = PROVIDER_LABELS[key_provider(req.harness)]
        raise HTTPException(status_code=400, detail=f"Informe a chave de API {provider} do projeto.")
    req.api_key = req.api_key.strip()
    effort = _checked_effort(req.harness, req.effort)

    identity = compose_project_identity(user, req.name)

    # Default repo path inside storage if not provided
    base_repo_path = req.repo_path or os.path.join(_get_storage_dir(), "projects", identity.project_id, "repo")
    os.makedirs(base_repo_path, exist_ok=True)

    default_branch = req.default_branch or "main"
    await git.init_repo(base_repo_path, default_branch=default_branch, initial_commit=True)

    repo_url = None
    if vcs:
        try:
            # Repositório privado na conta Gitea do usuário; o admin break-glass
            # (sem conta própria) cria na conta de serviço, também privado.
            owner = None
            if not user.is_admin:
                user = await ensure_gitea_account(request.app, user)
                if not user.gitea_username:
                    raise RuntimeError("usuário sem conta no Gitea")
                owner = user.gitea_username
            repo_info = await vcs.create_repository(
                name=identity.slug, description=req.description or "", private=True, owner=owner
            )
            await git.set_remote(base_repo_path, repo_info["clone_url_internal"], remote_name="origin")
            await git.push(base_repo_path, default_branch, remote_name="origin", set_upstream=True)
            repo_url = repo_info["web_url_external"]
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Could not link Gitea repo for {req.name} ({identity.slug}): {e}")

    project = await tracker.create_project(
        name=req.name,
        repo_path=base_repo_path,
        description=req.description or "",
        purpose=req.purpose or "",
        solution_description=req.solution_description or "",
        default_branch=default_branch,
        repo_url=repo_url,
        owner_id=None if user.is_admin else user.id,
        harness=req.harness,
        api_key=req.api_key,
        model=req.model,
        effort=effort,
        project_id=identity.project_id,
    )
    return _format_project(project)


@router.get("/{project_id}", dependencies=[Depends(require_project)])
async def get_project(project_id: str, request: Request):
    tracker = request.app.state.tracker
    project = await tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    return _format_project(project)


@router.put("/{project_id}", dependencies=[Depends(require_project)])
async def update_project(project_id: str, req: UpdateProjectRequest, request: Request):
    tracker = request.app.state.tracker
    current = await tracker.get_project(project_id)
    new_key = (req.api_key or "").strip() or None
    # Chave vazia mantém a atual, mas só enquanto o provedor não muda: uma chave
    # Gemini não serve a um harness DeepSeek, nem o contrário.
    if current and req.harness and new_key is None:
        if key_provider(req.harness) != key_provider(current.harness) or not current.api_key:
            provider = PROVIDER_LABELS[key_provider(req.harness)]
            raise HTTPException(
                status_code=400,
                detail=f"Este harness usa outro provedor: informe a chave de API {provider}.",
            )
    req.api_key = new_key
    # O esforço acompanha o harness efetivo: um harness sem o ajuste o apaga ("").
    effort = None
    if req.effort is not None or req.harness is not None:
        harness = req.harness or (current.harness if current else None)
        effort = _checked_effort(harness, req.effort if req.effort is not None else (current.effort if current else None)) or ""
    try:
        updated = await tracker.update_project(
            project_id=project_id,
            name=req.name,
            description=req.description,
            purpose=req.purpose,
            solution_description=req.solution_description,
            harness=req.harness,
            api_key=req.api_key,
            model=req.model,
            effort=effort,
        )
        return _format_project(updated)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{project_id}", dependencies=[Depends(require_project)])
async def delete_project(project_id: str, request: Request):
    tracker = request.app.state.tracker
    vcs = getattr(request.app.state, "vcs", None)
    project = await tracker.get_project(project_id)
    if vcs and project and project.repo_url:
        try:
            # Arquivado, não apagado: recuperável pelo admin do Gitea.
            await vcs.archive_repository(project.repo_url)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Could not archive Gitea repo of {project_id}: {e}")
    await tracker.delete_project(project_id)
    return {"status": "deleted", "project_id": project_id}


@router.post("/{project_id}/issues/sync", dependencies=[Depends(require_project)])
async def sync_issues(project_id: str, request: Request):
    """Mirror every task of the project into Gitea issues (creates the missing ones)."""
    tracker = request.app.state.tracker
    if not hasattr(tracker, "sync_project"):
        raise HTTPException(status_code=501, detail="Espelhamento de issues não está configurado")
    return await tracker.sync_project(project_id)


@router.post("/{project_id}/attachments", dependencies=[Depends(require_project)])
async def upload_attachment(project_id: str, file: UploadFile = File(...), request: Request = None):
    tracker = request.app.state.tracker
    project = await tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    storage_dir = os.path.join(_get_storage_dir(), "projects", project_id, "attachments")
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


@router.post("/{project_id}/start-interrogation", dependencies=[Depends(require_project)])
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


@router.post("/{project_id}/tasks", dependencies=[Depends(require_project)])
async def create_task(project_id: str, req: CreateTaskRequest, request: Request):
    tracker = request.app.state.tracker
    task = await tracker.create_task(
        project_id=project_id,
        title=req.title,
        description=req.description,
        target_files=req.target_files,
        acceptance_criteria=req.acceptance_criteria,
        dependencies=req.dependencies,
        session_id=req.session_id,
    )
    return task


@router.get("/{project_id}/tasks", dependencies=[Depends(require_project)])
async def list_tasks(project_id: str, request: Request, session_id: Optional[str] = None):
    tracker = request.app.state.tracker
    tasks = await tracker.list_tasks(project_id=project_id, session_id=session_id)
    return tasks


@router.get("/{project_id}/docs", dependencies=[Depends(require_project)])
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

    # 2. Backlogs: um por análise em .painkiller/backlogs/, mais o arquivo
    # único de versões anteriores, se ainda existir.
    backlog_files = sorted((repo_dir / ".painkiller" / "backlogs").glob("*.json"))
    legacy = repo_dir / ".painkiller" / "backlog.json"
    if legacy.is_file():
        backlog_files.append(legacy)
    for backlog_file in backlog_files:
        if not backlog_file.is_file():
            continue
        stat = backlog_file.stat()
        results.append({
            "path": backlog_file.relative_to(repo_dir).as_posix(),
            "filename": backlog_file.name,
            "category": "backlog",
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        })

    # Sort most recent first
    results.sort(key=lambda x: x["modified_at"], reverse=True)
    return results


@router.get("/{project_id}/docs/content", dependencies=[Depends(require_project)])
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


@router.get("/{project_id}/archive", dependencies=[Depends(require_project)])
async def download_project_archive(project_id: str, request: Request, ref: Optional[str] = None):
    """Download the repository as a zip (tracked files at ``ref``, default branch by default)."""
    tracker = request.app.state.tracker
    project = await tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    repo_dir = Path(project.repo_path).resolve()
    if not (repo_dir / ".git").exists():
        raise HTTPException(status_code=404, detail="Repositório local não encontrado")

    target = ref or project.default_branch
    if target.startswith("-"):
        raise HTTPException(status_code=400, detail="Referência inválida")

    try:
        data = await request.app.state.git.archive(str(repo_dir), target)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=f"Não foi possível gerar o zip de '{target}': {e}")

    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in project.name).strip("-") or project.id
    filename = f"{slug}-{target.replace('/', '-')}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
