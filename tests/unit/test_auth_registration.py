import pytest
from httpx import AsyncClient, ASGITransport
from painkiller.api.server import create_app

@pytest.mark.asyncio
async def test_registration_and_activation_flow(tmp_path):
    db_path = tmp_path / "test_auth.db"
    app = create_app(db_url=f"sqlite+aiosqlite:///{db_path.as_posix()}")
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Registrar usuário
            resp = await client.post("/api/auth/register", json={
                "first_name": "Ana",
                "last_name": "Silva",
                "email": "ana@example.com",
                "password": "Password123!",
                "confirm_password": "Password123!"
            })
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["email"] == "ana@example.com"
            assert data["status"] == "pending_verification"

            # 2. Tentar login antes de ativar (deve falhar 403)
            login_fail = await client.post("/api/auth/login", json={
                "username": "ana@example.com",
                "password": "Password123!"
            })
            assert login_fail.status_code == 403
            assert "ativada" in login_fail.json()["detail"].lower()

            # Obter código do banco para teste
            tracker = app.state.tracker
            user = await tracker.get_user_by_email_or_username("ana@example.com")
            assert user is not None
            code = user.verification_code
            assert len(code) == 6

            # 3. Testar código errado
            bad_code_resp = await client.post("/api/auth/verify-code", json={
                "email": "ana@example.com",
                "code": "000000"
            })
            assert bad_code_resp.status_code == 400

            # 4. Confirmar código correto
            verify_resp = await client.post("/api/auth/verify-code", json={
                "email": "ana@example.com",
                "code": code
            })
            assert verify_resp.status_code == 200
            assert "token" in verify_resp.json()
            assert verify_resp.json()["user"]["email"] == "ana@example.com"

            # 5. Login após ativação
            login_ok = await client.post("/api/auth/login", json={
                "username": "ana@example.com",
                "password": "Password123!"
            })
            assert login_ok.status_code == 200
            assert "token" in login_ok.json()

@pytest.mark.asyncio
async def test_registration_link_verification(tmp_path):
    db_path = tmp_path / "test_link.db"
    app = create_app(db_url=f"sqlite+aiosqlite:///{db_path.as_posix()}")

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            reg_resp = await client.post("/api/auth/register", json={
                "first_name": "Carlos",
                "last_name": "Souza",
                "email": "carlos@example.com",
                "password": "Password123!",
                "confirm_password": "Password123!"
            })
            assert reg_resp.status_code == 200

            tracker = app.state.tracker
            user = await tracker.get_user_by_email_or_username("carlos@example.com")
            token = user.verification_token
            assert token is not None

            # Ativar via link
            link_resp = await client.get(f"/api/auth/verify-link?token={token}", follow_redirects=False)
            assert link_resp.status_code == 302
            assert "login" in link_resp.headers["location"]
            assert "verified=true" in link_resp.headers["location"]

            # Confirmar que usuário ficou ativo
            activated = await tracker.get_user(user.id)
            assert activated.is_active is True
