"""Setup wizard: platform settings saved by the admin, resolved against the .env."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from painkiller.adapters.deployment.coolify_bootstrap import CoolifyBootstrapError, parse_result
from painkiller.adapters.sandbox import paths
from painkiller.api.server import create_app
from tests.auth_helpers import admin_headers, user_headers

GOOGLE_ID = "123-abc.apps.googleusercontent.com"


class FakeDocker:
    """Docker client with the harness images present and a probe container that echoes."""

    def __init__(self, mounts=None, echo=True):
        self.images = MagicMock()
        self.containers = MagicMock()
        self.containers.get.return_value = SimpleNamespace(attrs={"Mounts": mounts or []})
        self.echo = echo
        self.runs = []

        def run(image, command, volumes, **kwargs):
            self.runs.append((image, volumes))
            source = next(iter(volumes))
            if not self.echo:
                return b"outra-coisa"
            with open(f"{source}/.painkiller-mount-probe", "rb") as f:
                return f.read()

        self.containers.run.side_effect = run

    def ping(self):
        return True


class FakeCoolify:
    """Deployment adapter double: records configure() and answers check()."""

    def __init__(self):
        self.api_token = ""
        self.server_uuid = ""
        self.wildcard_domain = ""

    def configure(self, api_token=None, server_uuid=None, wildcard_domain=None):
        self.api_token, self.server_uuid, self.wildcard_domain = api_token, server_uuid, wildcard_domain

    def set_gitea_external_url(self, url):
        self.gitea_external_url = url

    async def check(self, api_token=None):
        token = self.api_token if api_token is None else api_token
        ok = token.startswith("1|")
        return {
            "reachable": True,
            "token_ok": ok,
            "version": "4.3.23" if ok else None,
            "servers": [{"uuid": "srv-1", "name": "localhost", "ip": "host", "usable": True}] if ok else [],
            "error": None if ok else "O Coolify recusou o token.",
        }


class FakeBootstrap:
    def __init__(self, created_user=True, error=None):
        self.created_user = created_user
        self.error = error
        self.calls = []

    async def inspect(self):
        return {"root_user": not self.created_user, "root_email": None, "api_enabled": False}

    async def provision(self, email, password):
        self.calls.append((email, password))
        if self.error:
            raise CoolifyBootstrapError(self.error)
        return {"token": "1|fresh-token", "email": email, "created_user": self.created_user}


def _make_app(db, docker=None):
    app = create_app(db_url=f"sqlite+aiosqlite:///{db}", deployment_adapter=FakeCoolify())
    app.state.platform.docker_client_factory = lambda: docker or FakeDocker()
    app.state.coolify_bootstrap = FakeBootstrap()
    # Nada de docker exec no Gitea de verdade da máquina.
    app.state.vcs.ensure_root_url = AsyncMock(return_value=False)
    return app


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "PAINKILLER_PUBLIC_URL", "PAINKILLER_HOST_ROOT", "PAINKILLER_CONTAINER_ROOT",
        "COOLIFY_API_TOKEN", "COOLIFY_SERVER_UUID", "COOLIFY_WILDCARD_DOMAIN", "COOLIFY_PORT",
        "PAINKILLER_GITEA_EXTERNAL_URL", "PAINKILLER_GOOGLE_REDIRECT_URI",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    paths.set_host_root(None)


@pytest.fixture
async def app(tmp_path):
    app = _make_app(tmp_path / "setup.db")
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://painel.local:8000", headers=admin_headers()) as c:
        yield c


async def test_setup_is_admin_only(app, client):
    alice = await app.state.tracker.create_user(email="alice@example.com")
    assert (await client.get("/api/setup", headers=user_headers(alice.id))).status_code == 403


async def test_fresh_install_prefills_from_the_request(client):
    state = (await client.get("/api/setup")).json()
    assert state["completed"] is False
    assert state["steps"] == {"environment": "pending", "google": "pending", "coolify": "pending"}
    env = state["environment"]
    assert env["public_url"] == "http://painel.local:8000"
    assert env["docker_ok"] is True and all(row["present"] for row in env["images"])
    # Tudo que deriva da URL pública concorda com a URL que o admin está usando.
    google = state["google"]
    assert google["redirect_uris"]["painkiller"] == "http://painel.local:8000/api/auth/google/callback"
    assert google["redirect_uris"]["gitea"] == "http://painel.local:8000/gitea/user/oauth2/google/callback"
    assert state["coolify"]["dashboard_url"] == "http://painel.local:8008"


async def test_env_does_not_configure_the_platform(client, monkeypatch):
    # O .env não é mais fallback: só o que foi salvo no banco conta.
    monkeypatch.setenv("PAINKILLER_GOOGLE_CLIENT_ID", GOOGLE_ID)
    monkeypatch.setenv("PAINKILLER_GOOGLE_CLIENT_SECRET", "from-env")
    monkeypatch.setenv("COOLIFY_API_TOKEN", "1|env-token")
    monkeypatch.setenv("PAINKILLER_HOST_ROOT", "/from/env")
    state = (await client.get("/api/setup")).json()
    assert state["steps"] == {"environment": "pending", "google": "pending", "coolify": "pending"}
    assert state["google"]["client_id"] == "" and state["google"]["enabled"] is False
    assert state["coolify"]["has_token"] is False
    assert state["environment"]["host_root"] is None


async def test_google_step_applies_without_restart_and_seals_the_secret(app, client):
    bad = await client.put("/api/setup/google", json={"client_id": "not-a-client", "client_secret": "s"})
    assert bad.status_code == 400

    res = await client.put(
        "/api/setup/google",
        json={"client_id": GOOGLE_ID, "client_secret": "super-secret-value", "allowed_domains": "empresa.com.br"},
    )
    assert res.status_code == 200
    state = res.json()
    assert state["steps"]["google"] == "done"
    assert state["google"]["enabled"] is True
    assert "super-secret-value" not in str(state)

    google = app.state.google_oauth
    assert google.enabled and google.client_secret == "super-secret-value"
    assert google.allowed_domain_set == {"empresa.com.br"}
    assert (await client.get("/api/auth/config")).json()["google"] is True

    raw = await app.state.tracker._read_setting("platform")
    assert "super-secret-value" not in raw

    # Vazio mantém o secret salvo.
    kept = await client.put("/api/setup/google", json={"client_id": GOOGLE_ID, "allowed_domains": ""})
    assert kept.status_code == 200
    assert app.state.google_oauth.client_secret == "super-secret-value"


async def test_settings_survive_a_restart(tmp_path):
    db = tmp_path / "restart.db"
    first = _make_app(db)
    async with first.router.lifespan_context(first):
        async with AsyncClient(transport=ASGITransport(app=first), base_url="http://t", headers=admin_headers()) as c:
            await c.put("/api/setup/google", json={"client_id": GOOGLE_ID, "client_secret": "kept"})
            await c.post("/api/setup/complete")

    second = _make_app(db)
    async with second.router.lifespan_context(second):
        assert second.state.google_oauth.client_secret == "kept"
        assert second.state.platform.settings.completed is True


async def test_coolify_manual_token_is_checked_before_saving(app, client):
    refused = await client.put("/api/setup/coolify", json={"api_token": "wrong"})
    assert refused.status_code == 400

    res = await client.put("/api/setup/coolify", json={"api_token": "1|manual", "wildcard_domain": "apps.example.com."})
    assert res.status_code == 200
    assert res.json()["steps"]["coolify"] == "done"
    deployment = app.state.deployment
    assert deployment.api_token == "1|manual"
    assert deployment.wildcard_domain == "apps.example.com"
    # Um servidor só: nada a escolher.
    assert deployment.server_uuid == "srv-1"


async def test_coolify_bootstrap_saves_token_and_root_credentials(app, client):
    res = await client.post("/api/setup/coolify/bootstrap", json={"email": "ops@example.com"})
    assert res.status_code == 200
    body = res.json()
    assert body["created_user"] is True and body["password"]
    assert body["api"]["token_ok"] is True
    assert body["state"]["steps"]["coolify"] == "done"
    assert app.state.deployment.api_token == "1|fresh-token"

    creds = (await client.get("/api/setup/coolify/credentials")).json()
    assert creds == {"email": "ops@example.com", "password": body["password"]}
    raw = await app.state.tracker._read_setting("platform")
    assert body["password"] not in raw and "1|fresh-token" not in raw


async def test_coolify_bootstrap_keeps_an_existing_account_password(app, client):
    app.state.coolify_bootstrap = FakeBootstrap(created_user=False)
    body = (await client.post("/api/setup/coolify/bootstrap", json={})).json()
    assert body["password"] is None
    assert (await client.get("/api/setup/coolify/credentials")).status_code == 404


async def test_coolify_bootstrap_failure_is_reported(app, client):
    app.state.coolify_bootstrap = FakeBootstrap(error="O contêiner painkiller-coolify não está rodando (exited).")
    res = await client.post("/api/setup/coolify/bootstrap", json={})
    assert res.status_code == 502
    assert "não está rodando" in res.json()["detail"]


async def test_skip_and_complete(client):
    assert (await client.post("/api/setup/steps/environment/skip")).status_code == 400
    state = (await client.post("/api/setup/steps/google/skip")).json()
    assert state["steps"]["google"] == "skipped"
    state = (await client.post("/api/setup/complete")).json()
    assert state["completed"] is True


async def test_mount_probe_reads_the_sentinel_through_the_daemon_path(tmp_path, isolate_test_storage):
    docker = FakeDocker()
    app = _make_app(tmp_path / "probe.db", docker=docker)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=admin_headers()) as c:
            ok = (await c.post("/api/setup/environment/test")).json()
            assert ok["ok"] is True, ok
            docker.echo = False
            bad = (await c.post("/api/setup/environment/test")).json()
            assert bad["ok"] is False
    assert not (isolate_test_storage / ".painkiller-mount-probe").exists()


async def test_host_root_is_detected_from_our_own_container(tmp_path, monkeypatch):
    monkeypatch.setenv("PAINKILLER_CONTAINER_ROOT", "/app/storage")
    docker = FakeDocker(mounts=[
        {"Type": "volume", "Destination": "/data", "Source": "/var/lib/docker/volumes/x"},
        {"Type": "bind", "Destination": "/app/storage", "Source": "/run/desktop/mnt/host/d/pk/storage"},
    ])
    app = _make_app(tmp_path / "detect.db", docker=docker)
    async with app.router.lifespan_context(app):
        assert app.state.platform.host_root() == ("/run/desktop/mnt/host/d/pk/storage", "detected")
        assert paths.daemon_path("/app/storage/projects/p/repo") == "/run/desktop/mnt/host/d/pk/storage/projects/p/repo"

        # O que o admin salva vence a detecção.
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=admin_headers()) as c:
            await c.put("/api/setup/environment", json={"public_url": "http://10.0.0.5:8000", "host_root": "D:\\pk\\storage"})
        assert paths.daemon_path("/app/storage/x") == "D:\\pk\\storage\\x"
        assert app.state.platform.coolify_values()["wildcard_domain"] == "10.0.0.5.nip.io"


def test_parse_result_ignores_tinker_noise():
    out = "Deprecated: foo\nPAINKILLER_JSON:{\"token\": \"1|x\"}\n"
    assert parse_result(out) == {"token": "1|x"}
    with pytest.raises(CoolifyBootstrapError):
        parse_result("Illuminate\\Database\\QueryException ...")


async def test_gitea_service_password_is_generated_sealed_and_applied(tmp_path):
    db = tmp_path / "gitea.db"
    first = _make_app(db)
    async with first.router.lifespan_context(first):
        password = first.state.vcs.password
        assert len(password) >= 24
        # O push usa a mesma credencial, sem nada no .env.
        assert first.state.git.http_credentials[first.state.vcs.internal_base_url] == ("painkiller", password)
        raw = await first.state.tracker._read_setting("platform")
        assert password not in raw

    second = _make_app(db)
    async with second.router.lifespan_context(second):
        assert second.state.vcs.password == password  # estável entre restarts


async def test_public_url_drives_gitea_links_and_session_ttl(app, client, monkeypatch):
    from painkiller.api import security

    monkeypatch.setenv("PAINKILLER_GITEA_EXTERNAL_URL", "http://ignored:1/gitea")
    res = await client.put(
        "/api/setup/environment", json={"public_url": "https://pk.example.com", "session_ttl_hours": 48}
    )
    assert res.status_code == 200
    assert app.state.vcs.external_base_url == "https://pk.example.com/gitea"
    assert app.state.deployment.gitea_external_url == "https://pk.example.com/gitea"
    assert res.json()["google"]["redirect_uris"]["gitea"] == "https://pk.example.com/gitea/user/oauth2/google/callback"
    assert res.json()["environment"]["session_ttl_hours"] == 48
    assert security._session_ttl_seconds == 48 * 3600

    too_long = await client.put("/api/setup/environment", json={"public_url": "", "session_ttl_hours": 10000})
    assert too_long.status_code == 400


async def test_gitea_root_url_is_rewritten_only_when_it_changes():
    from painkiller.adapters.vcs.gitea_adapter import GiteaAdapter

    container = MagicMock()
    state = {"root": "http://localhost:8000/gitea/"}

    def exec_run(cmd, user=None, environment=None):
        if cmd[0] == "sh":
            return 0, f"ROOT_URL = {state['root']}\n".encode()
        state["root"] = environment["GITEA__server__ROOT_URL"]
        return 0, b""

    container.exec_run.side_effect = exec_run
    docker = MagicMock()
    docker.containers.get.return_value = container
    adapter = GiteaAdapter(docker_client=docker)

    assert await adapter.ensure_root_url("http://localhost:8000/gitea") is False
    container.restart.assert_not_called()

    assert await adapter.ensure_root_url("https://pk.example.com/gitea") is True
    assert state["root"] == "https://pk.example.com/gitea/"
    container.restart.assert_called_once()
