"""Deployments API routes for test and production environments."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from painkiller.api.security import current_user, visible_project
from painkiller.core.domain.models import DeploymentComponent, DeploymentRecord, EnvironmentType, User
from painkiller.engine.deployment_service import (
    BackendMissingError,
    BranchPushError,
    BranchUnavailableError,
    DeploymentNotFailedError,
)

router = APIRouter(tags=["deployments"])


class TriggerDeployRequest(BaseModel):
    environment: EnvironmentType
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    # O app (build web) ou o backend/: cada um é uma aplicação no Coolify.
    component: DeploymentComponent = DeploymentComponent.APP


@router.post("/api/projects/{project_id}/deploy", response_model=DeploymentRecord)
async def trigger_deploy(
    project_id: str,
    body: TriggerDeployRequest,
    request: Request,
    user: User = Depends(current_user),
):
    """Trigger an automated deployment of test or production environment."""
    project = await visible_project(request, project_id)
    deployment_service = request.app.state.deployment_service

    try:
        record = await deployment_service.trigger_deploy(
            project_id=project.id,
            environment=body.environment,
            task_id=body.task_id,
            session_id=body.session_id,
            component=body.component,
        )
        return record
    except BackendMissingError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except BranchUnavailableError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except BranchPushError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao disparar deploy: {e}")


@router.get("/api/projects/{project_id}/deployments", response_model=list[DeploymentRecord])
async def list_project_deployments(
    project_id: str,
    request: Request,
    user: User = Depends(current_user),
    limit: int = 20,
):
    """List recent deployment records for a project."""
    project = await visible_project(request, project_id)
    deployment_service = request.app.state.deployment_service
    return await deployment_service.list_project_deployments(project.id, limit=limit)


@router.get("/api/projects/{project_id}/deployments/status")
async def get_environment_status(
    project_id: str,
    request: Request,
    user: User = Depends(current_user),
):
    """Get active URLs and latest deployment status for test and production environments."""
    project = await visible_project(request, project_id)
    deployment_service = request.app.state.deployment_service
    return await deployment_service.get_project_environment_status(project.id)


@router.get("/api/deployments/{deployment_id}", response_model=DeploymentRecord)
async def get_deployment(
    deployment_id: str,
    request: Request,
    user: User = Depends(current_user),
):
    """Get a deployment record with refreshed live status."""
    deployment_service = request.app.state.deployment_service
    record = await deployment_service.get_deployment(deployment_id)
    if not record:
        raise HTTPException(status_code=404, detail="Deploy não encontrado")

    # Garante que o usuário tem acesso ao projeto deste deploy
    await visible_project(request, record.project_id)
    return record


@router.post("/api/deployments/{deployment_id}/fix")
async def create_deployment_fix_task(
    deployment_id: str,
    request: Request,
    user: User = Depends(current_user),
):
    """Create (or reuse) a task asking the agent to fix a failed deploy."""
    deployment_service = request.app.state.deployment_service
    record = await deployment_service.tracker.get_deployment(deployment_id)
    if not record:
        raise HTTPException(status_code=404, detail="Deploy não encontrado")
    await visible_project(request, record.project_id)

    try:
        return await deployment_service.create_fix_task(deployment_id)
    except DeploymentNotFailedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
