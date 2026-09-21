"""Unit tests for GiteaAdapter."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from painkiller.adapters.vcs.gitea_adapter import GiteaAdapter


def test_slugify_name():
    assert GiteaAdapter.slugify_name("My New Project 2026!") == "my-new-project-2026"
    assert GiteaAdapter.slugify_name("Painkiller Engine") == "painkiller-engine"
    assert GiteaAdapter.slugify_name("Projeto_Teste") == "projeto_teste"


def test_url_helpers():
    adapter = GiteaAdapter(
        internal_base_url="http://gitea:3000",
        external_base_url="http://localhost:3000",
        username="painkiller",
    )
    branch_url = adapter.get_branch_url("My Project", "feature/task-1")
    assert branch_url == "http://localhost:3000/painkiller/my-project/src/branch/feature/task-1"

    diff_url = adapter.get_diff_url("My Project", "feature/task-1", "main")
    assert diff_url == "http://localhost:3000/painkiller/my-project/compare/main...feature/task-1"

    commit_url = adapter.get_commit_url("My Project", "abc1234")
    assert commit_url == "http://localhost:3000/painkiller/my-project/commit/abc1234"


@pytest.mark.asyncio
async def test_create_repository_success():
    adapter = GiteaAdapter(
        internal_base_url="http://gitea:3000",
        external_base_url="http://localhost:3000",
        username="painkiller",
        password="secretpassword",
    )

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 201
    mock_response.json.return_value = {"name": "app"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        res = await adapter.create_repository("App", "My app description")

        assert res["name"] == "app"
        assert res["clone_url_internal"] == "http://painkiller:secretpassword@gitea:3000/painkiller/app.git"
        assert res["web_url_external"] == "http://localhost:3000/painkiller/app"
