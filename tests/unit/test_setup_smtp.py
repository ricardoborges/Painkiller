import pytest
from httpx import AsyncClient, ASGITransport
from painkiller.api.server import create_app
from painkiller.api.security import issue_token, BREAK_GLASS_ID, break_glass_fingerprint

@pytest.mark.asyncio
async def test_setup_smtp_save_and_state(tmp_path):
    db_path = tmp_path / "test_smtp.db"
    app = create_app(db_url=f"sqlite+aiosqlite:///{db_path.as_posix()}")
    admin_token = issue_token(BREAK_GLASS_ID, pw=break_glass_fingerprint())
    headers = {"Authorization": f"Bearer {admin_token}"}

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Salvar configuração SMTP
            resp = await client.put("/api/setup/smtp", headers=headers, json={
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "smtp_user": "admin@gmail.com",
                "smtp_password": "mypassword123",
                "smtp_from": "no-reply@painkiller.io",
                "smtp_tls": True
            })
            assert resp.status_code == 200, resp.text
            state = resp.json()
            assert "smtp" in state
            assert state["smtp"]["smtp_host"] == "smtp.gmail.com"
            assert state["smtp"]["smtp_port"] == 587
            assert state["smtp"]["smtp_user"] == "admin@gmail.com"
            assert state["smtp"]["smtp_password_set"] is True

            # 2. Atualizar sem mudar a senha
            resp2 = await client.put("/api/setup/smtp", headers=headers, json={
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 465,
                "smtp_user": "admin@gmail.com",
                "smtp_password": "",
                "smtp_from": "no-reply@painkiller.io",
                "smtp_tls": False
            })
            assert resp2.status_code == 200
            state2 = resp2.json()
            assert state2["smtp"]["smtp_port"] == 465
            assert state2["smtp"]["smtp_password_set"] is True

            # Verificar que a senha continua salva no banco
            loaded = await app.state.platform.load()
            assert loaded.smtp_password == "mypassword123"
