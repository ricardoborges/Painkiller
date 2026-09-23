"""Unit tests for DeploymentService."""

import pytest
from unittest.mock import AsyncMock
from painkiller.core.domain.models import (
    Project,
    Task,
    TaskStatus,
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
    task = Task(id="task-10", project_id="proj-1", title="Feature X", description="Desc",
                status=TaskStatus.COMPLETED, assigned_branch="feature/task-10")

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
async def test_test_deploy_without_task_skips_unpushed_branches():
    """A RUNNING task's branch was never pushed; the last COMPLETED one was."""
    mock_tracker = AsyncMock()
    mock_deployment = AsyncMock()

    project = Project(id="proj-1", name="App", repo_path="/tmp", default_branch="main")
    mock_tracker.get_project.return_value = project
    mock_tracker.list_tasks.return_value = [
        Task(id="t1", project_id="proj-1", title="A", description="d",
             status=TaskStatus.COMPLETED, assigned_branch="feature/t1"),
        Task(id="t2", project_id="proj-1", title="B", description="d",
             status=TaskStatus.RUNNING, assigned_branch="feature/t2"),
        Task(id="t3", project_id="proj-1", title="C", description="d"),
    ]
    mock_tracker.save_deployment.side_effect = lambda rec: rec
    mock_deployment.deploy_environment.return_value = DeploymentRecord(
        id="dep-3", project_id="proj-1", environment=EnvironmentType.TEST,
        branch="feature/t1", status=DeploymentStatus.BUILDING,
    )

    service = DeploymentService(tracker=mock_tracker, deployment=mock_deployment)
    await service.trigger_deploy(project_id="proj-1", environment=EnvironmentType.TEST)

    assert mock_deployment.deploy_environment.call_args.kwargs["branch"] == "feature/t1"
    assert mock_deployment.deploy_environment.call_args.kwargs["task_id"] == "t1"


@pytest.mark.asyncio
async def test_test_deploy_with_running_task_falls_back_to_last_completed():
    mock_tracker = AsyncMock()
    mock_deployment = AsyncMock()

    project = Project(id="proj-1", name="App", repo_path="/tmp", default_branch="main")
    running = Task(id="t2", project_id="proj-1", title="B", description="d",
                   status=TaskStatus.RUNNING, assigned_branch="feature/t2")
    mock_tracker.get_project.return_value = project
    mock_tracker.get_task.return_value = running
    mock_tracker.list_tasks.return_value = [
        Task(id="t1", project_id="proj-1", title="A", description="d",
             status=TaskStatus.COMPLETED, assigned_branch="feature/t1"),
        running,
    ]
    mock_tracker.save_deployment.side_effect = lambda rec: rec
    mock_deployment.deploy_environment.return_value = DeploymentRecord(
        id="dep-5", project_id="proj-1", environment=EnvironmentType.TEST,
        branch="feature/t1", status=DeploymentStatus.BUILDING,
    )

    service = DeploymentService(tracker=mock_tracker, deployment=mock_deployment)
    await service.trigger_deploy(project_id="proj-1", environment=EnvironmentType.TEST, task_id="t2")

    assert mock_deployment.deploy_environment.call_args.kwargs["branch"] == "feature/t1"
    assert mock_deployment.deploy_environment.call_args.kwargs["task_id"] == "t1"


@pytest.mark.asyncio
async def test_test_deploy_without_completed_task_uses_default_branch():
    mock_tracker = AsyncMock()
    mock_deployment = AsyncMock()

    project = Project(id="proj-1", name="App", repo_path="/tmp", default_branch="main")
    mock_tracker.get_project.return_value = project
    mock_tracker.list_tasks.return_value = [
        Task(id="t2", project_id="proj-1", title="B", description="d",
             status=TaskStatus.RUNNING, assigned_branch="feature/t2"),
    ]
    mock_tracker.save_deployment.side_effect = lambda rec: rec
    mock_deployment.deploy_environment.return_value = DeploymentRecord(
        id="dep-4", project_id="proj-1", environment=EnvironmentType.TEST,
        branch="main", status=DeploymentStatus.BUILDING,
    )

    service = DeploymentService(tracker=mock_tracker, deployment=mock_deployment)
    await service.trigger_deploy(project_id="proj-1", environment=EnvironmentType.TEST)

    assert mock_deployment.deploy_environment.call_args.kwargs["branch"] == "main"
    assert mock_deployment.deploy_environment.call_args.kwargs["task_id"] is None


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
