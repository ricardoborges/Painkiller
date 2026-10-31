"""Project secrets: API keys of the services the app calls, write-only.

Nenhuma rota devolve um valor: a lista traz nome, escopo e data. Os valores só
saem do banco para os builds do app (VITE_*) e para o backend no Coolify.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from painkiller.api.security import require_project
from painkiller.core.domain.models import ProjectSecret, SecretScope
from painkiller.core.secrets import SecretNameError, check_secret

router = APIRouter(
    prefix="/api/projects/{project_id}/secrets",
    tags=["secrets"],
    dependencies=[Depends(require_project)],
)

#: Uma chave de API cabe folgada; um arquivo inteiro não é segredo de ambiente.
MAX_VALUE_LENGTH = 16_384


class PutSecretRequest(BaseModel):
    scope: SecretScope
    value: str


@router.get("", response_model=list[ProjectSecret])
async def list_secrets(project_id: str, request: Request):
    return await request.app.state.tracker.list_secrets(project_id)


@router.put("/{name}", response_model=ProjectSecret)
async def put_secret(project_id: str, name: str, body: PutSecretRequest, request: Request):
    try:
        name = check_secret(name, body.scope)
    except SecretNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Espaços e quebras nas pontas vêm de copiar e colar, nunca da chave.
    value = body.value.strip()
    if not value:
        raise HTTPException(status_code=400, detail="Informe o valor do segredo.")
    if len(value) > MAX_VALUE_LENGTH:
        raise HTTPException(status_code=400, detail="Valor grande demais para um segredo.")
    return await request.app.state.tracker.put_secret(project_id, name, body.scope, value)


@router.delete("/{name}")
async def delete_secret(project_id: str, name: str, request: Request):
    tracker = request.app.state.tracker
    removed = await tracker.delete_secret(project_id, name)
    if removed is None:
        raise HTTPException(status_code=404, detail="Segredo não encontrado")
    project = await tracker.get_project(project_id)
    if project is not None:
        await request.app.state.deployment_service.remove_secret(project, removed)
    return {"status": "deleted", "name": removed.name}
