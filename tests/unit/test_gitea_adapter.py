"""Unit tests for GiteaAdapter."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from painkiller.adapters.vcs.gitea_adapter import GiteaAdapter


def test_slugify_name():
    assert GiteaAdapter.slugify_name("My New Project 2026!") == "my-new-project-2026"
    assert GiteaAdapter.slugify_name("Painkiller Engine") == "painkiller-engine"
    assert GiteaAdapter.slugify_name("Projeto_Teste") == "projeto_teste"
    # O Gitea recusa nomes fora de [A-Za-z0-9_.-].
    assert GiteaAdapter.slugify_name("Gestão de Ações") == "gestao-de-acoes"
    assert GiteaAdapter.slugify_name("日本") == "project"


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
        assert res["clone_url_internal"] == "http://gitea:3000/painkiller/app.git"
        assert res["web_url_external"] == "http://localhost:3000/painkiller/app"


def test_username_candidate():
    assert GiteaAdapter.username_candidate("Maria.Silva+dev@gmail.com") == "maria-silva-dev"
    assert GiteaAdapter.username_candidate("___@x.com") == "user"


def test_find_auth_source():
    listing = "ID\tName\tType\tEnabled\n1\tldap\tLDAP\ttrue\n3   google   OAuth2   true\n"
    assert GiteaAdapter._find_auth_source(listing, "google") == 3
    assert GiteaAdapter._find_auth_source(listing, "github") is None


def _response(status: int, payload=None, text: str = ""):
    res = MagicMock(spec=httpx.Response)
    res.status_code = status
    res.json.return_value = payload or {}
    res.text = text
    return res


@pytest.mark.asyncio
async def test_create_repository_for_owner_is_private_under_their_account():
    adapter = GiteaAdapter(
        internal_base_url="http://gitea:3000",
        external_base_url="http://localhost:3300",
        username="painkiller",
        password="pw",
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _response(201)
        res = await adapter.create_repository("Loja", owner="alice", private=False)

    url = mock_post.call_args.args[0]
    assert url == "http://gitea:3000/api/v1/admin/users/alice/repos"
    assert mock_post.call_args.kwargs["json"]["private"] is True
    assert res["web_url_external"] == "http://localhost:3300/alice/loja"
    # Sem credencial: a URL vai para o .git/config, que o agente lê.
    assert res["clone_url_internal"] == "http://gitea:3000/alice/loja.git"


@pytest.mark.asyncio
async def test_create_repository_never_reuses_a_taken_name():
    adapter = GiteaAdapter(
        internal_base_url="http://gitea:3000",
        external_base_url="http://localhost:3300",
        username="painkiller",
        password="pw",
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [_response(409), _response(409), _response(201)]
        res = await adapter.create_repository("Loja", owner="alice")

    names = [c.kwargs["json"]["name"] for c in mock_post.call_args_list]
    assert names == ["loja", "loja-2", "loja-3"]
    assert res["name"] == "loja-3"
    assert res["web_url_external"] == "http://localhost:3300/alice/loja-3"


@pytest.mark.asyncio
async def test_archive_repository_parses_web_url():
    adapter = GiteaAdapter(
        internal_base_url="http://gitea:3000",
        external_base_url="http://localhost:3300",
        username="painkiller",
        password="pw",
    )
    with patch("httpx.AsyncClient.patch", new_callable=AsyncMock) as mock_patch:
        mock_patch.return_value = _response(200)
        assert await adapter.archive_repository("http://localhost:3300/alice/loja-2") is True
        # Repositório fora deste Gitea não é tocado.
        assert await adapter.archive_repository("https://github.com/alice/loja") is False

    assert mock_patch.call_count == 1
    assert mock_patch.call_args.args[0] == "http://gitea:3000/api/v1/repos/alice/loja-2"
    assert mock_patch.call_args.kwargs["json"] == {"archived": True}


def test_push_credentials_are_keyed_by_internal_url():
    adapter = GiteaAdapter(internal_base_url="http://gitea:3000/", username="painkiller", password="pw")
    assert adapter.push_credentials() == {"http://gitea:3000": ("painkiller", "pw")}


@pytest.mark.asyncio
async def test_ensure_user_creates_private_account_linked_to_google():
    adapter = GiteaAdapter(internal_base_url="http://gitea:3000", username="painkiller", password="pw")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _response(201)
        login = await adapter.ensure_user("alice@example.com", "Alice", oauth_source_id=3, oauth_login_name="g-1")

    assert login == "alice"
    payload = mock_post.call_args.kwargs["json"]
    assert payload["visibility"] == "private"
    assert payload["source_id"] == 3 and payload["login_name"] == "g-1"


@pytest.mark.asyncio
async def test_ensure_user_skips_taken_login_and_reuses_own_account():
    adapter = GiteaAdapter(internal_base_url="http://gitea:3000", username="painkiller", password="pw")
    taken = _response(422, text="user already exists [name: alice]")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
            patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        # "alice" é de outra pessoa; "alice-2" já é desta (banco do Painkiller perdido).
        mock_post.side_effect = [taken, taken]
        mock_get.side_effect = [
            _response(200, {"email": "other@example.com"}),
            _response(200, {"email": "Alice@example.com"}),
        ]
        login = await adapter.ensure_user("alice@example.com")

    assert login == "alice-2"


@pytest.mark.asyncio
async def test_add_deploy_key_replaces_orphan_with_same_title():
    """A key left behind by a failed deploy would make Gitea answer 422 forever."""
    adapter = GiteaAdapter(internal_base_url="http://gitea:3000", username="painkiller", password="pw")
    calls = []

    async def fake_api(method, path, **kwargs):
        calls.append((method, path))
        if method == "GET":
            return _response(200, [{"id": 7, "title": "painkiller-damas"}, {"id": 8, "title": "outra"}])
        return _response(201 if method == "POST" else 204)

    with patch.object(adapter, "_api", side_effect=fake_api):
        await adapter.add_deploy_key("alice", "damas", "painkiller-damas", "ssh-ed25519 AAA")

    assert calls == [
        ("GET", "/repos/alice/damas/keys"),
        ("DELETE", "/repos/alice/damas/keys/7"),
        ("POST", "/repos/alice/damas/keys"),
    ]
