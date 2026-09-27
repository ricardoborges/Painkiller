import pytest
from datetime import datetime, timezone, timedelta
from painkiller.core.domain.models import PlatformSettings, User
from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker

@pytest.mark.asyncio
async def test_user_extended_fields(tmp_path):
    db_file = tmp_path / "test.db"
    tracker = SQLiteIssueTracker(f"sqlite+aiosqlite:///{db_file}")
    await tracker.init_db()

    # Criação de usuário com campos de registro e verificação
    user = await tracker.create_user(
        email="test@example.com",
        name="Test User",
        password_hash="scrypt$fakehash",
        is_active=False,
        email_verified=False,
        verification_code="123456",
        verification_token="token-abc-123",
        verification_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    assert user.email == "test@example.com"
    assert user.is_active is False
    assert user.email_verified is False

    # Busca por email ou username
    fetched = await tracker.get_user_by_email_or_username("test@example.com")
    assert fetched is not None
    assert fetched.id == user.id

    # Busca por token de verificação
    by_token = await tracker.get_user_by_verification_token("token-abc-123")
    assert by_token is not None
    assert by_token.id == user.id

    # Atualização de ativação
    updated = await tracker.activate_user(user.id)
    assert updated.is_active is True
    assert updated.email_verified is True
    assert updated.verification_code is None
    assert updated.verification_token is None

@pytest.mark.asyncio
async def test_platform_settings_smtp_fields(tmp_path):
    db_file = tmp_path / "test.db"
    tracker = SQLiteIssueTracker(f"sqlite+aiosqlite:///{db_file}")
    await tracker.init_db()

    settings = PlatformSettings(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="mailer",
        smtp_password="super-secret-password",
        smtp_from="noreply@example.com",
        smtp_tls=True,
    )
    await tracker.save_platform_settings(settings)

    loaded = await tracker.get_platform_settings()
    assert loaded.smtp_host == "smtp.example.com"
    assert loaded.smtp_port == 587
    assert loaded.smtp_password == "super-secret-password"
