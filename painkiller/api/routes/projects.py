"""Project routes."""

from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str
    repo_path: str
    default_branch: str = "main"


class CreateTaskRequest(BaseModel):
    title: str
    description: str
    target_files: Optional[list[str]] = None
    acceptance_criteria: Optional[list[str]] = None
    dependencies: Optional[list[str]] = None


@router.post("")
async def create_project(req: CreateProjectRequest, request: Request):
    tracker = request.app.state.tracker
    project = await tracker.create_project(
        name=req.name,
        repo_path=req.repo_path,
        default_branch=req.default_branch,
    )
    return project


@router.get("/{project_id}")
async def get_project(project_id: str, request: Request):
    tracker = request.app.state.tracker
    project = await tracker.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


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
