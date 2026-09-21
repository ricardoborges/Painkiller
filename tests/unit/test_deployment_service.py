"""Unit tests for DeploymentService."""

import pytest
from unittest.mock import AsyncMock
from painkiller.core.domain.models import (
    Project,
    Task,
    DeploymentRecord,
    DeploymentStatus,
    EnvironmentType,
)
from painkiller.engine.deployment_service import DeploymentService


@pytest.mark.asyncio
async def test_deployment_service_test_branch_resolution():
    mock_tracker = AsyncMock()
    mock_deployment = AsyncMock()

    project = Project(id="proj-1", name="App", repo_path="/tmp", default_branch="main")
    task = Task(id="task-10", project_id="proj-1", title="Feature X", description="Desc", assigned_branch="feature/task-10")

    mock_tracker.get_project.return_value = project
    mock_tracker.get_task.return_value = task
    mock_tracker.save_deployment.side_effect = lambda rec: rec

    returned_rec = DeploymentRecord(
        id="dep-1",
        project_id="proj-1",
        task_id="task-10",
        environment=EnvironmentType.TEST,
        branch="feature/task-10",
        status=DeploymentStatus.BUILDING,
        url="http://app-test.local",
    )
    mock_deployment.deploy_environment.return_value = returned_rec

    service = DeploymentService(tracker=mock_tracker, deployment=mock_deployment)
    result = await service.trigger_deploy(
        project_id="proj-1",
        environment=EnvironmentType.TEST,
        task_id="task-10",
    )

    assert result.branch == "feature/task-10"
    mock_deployment.deploy_environment.assert_called_once_with(
        project=project,
        environment=EnvironmentType.TEST,
        branch="feature/task-10",
        task_id="task-10",
        session_id=None,
    )
    mock_tracker.update_project_deployment_urls.assert_called_once_with("proj-1", test_url="http://app-test.local")


@pytest.mark.asyncio
async def test_deployment_service_production_always_uses_main():
    mock_tracker = AsyncMock()
    mock_deployment = AsyncMock()

    project = Project(id="proj-1", name="App", repo_path="/tmp", default_branch="main")
    mock_tracker.get_project.return_value = project
    mock_tracker.save_deployment.side_effect = lambda rec: rec

    returned_rec = DeploymentRecord(
        id="dep-2",
        project_id="proj-1",
        environment=EnvironmentType.PRODUCTION,
        branch="main",
        status=DeploymentStatus.HEALTHY,
        url="http://app-prod.local",
    )
    mock_deployment.deploy_environment.return_value = returned_rec

    service = DeploymentService(tracker=mock_tracker, deployment=mock_deployment)
    result = await service.trigger_deploy(
        project_id="proj-1",
        environment=EnvironmentType.PRODUCTION,
        task_id="task-ignored",
    )

    assert result.branch == "main"
    mock_deployment.deploy_environment.assert_called_once_with(
        project=project,
        environment=EnvironmentType.PRODUCTION,
        branch="main",
        task_id="task-ignored",
        session_id=None,
    )
    mock_tracker.update_project_deployment_urls.assert_called_once_with("proj-1", production_url="http://app-prod.local")
