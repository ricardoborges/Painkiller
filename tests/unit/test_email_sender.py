import logging
import pytest
from unittest.mock import patch, MagicMock
from painkiller.core.domain.models import PlatformSettings
from painkiller.adapters.email.smtp_sender import EmailSender

@pytest.mark.asyncio
async def test_email_sender_fallback_logger(caplog):
    sender = EmailSender(settings_provider=lambda: PlatformSettings())
    with caplog.at_level(logging.INFO):
        await sender.send_verification_email(
            to_email="test@domain.com",
            name="John Doe",
            code="654321",
            link="http://localhost:8000/api/auth/verify-link?token=xyz",
        )
    assert "654321" in caplog.text
    assert "test@domain.com" in caplog.text
    assert "verify-link?token=xyz" in caplog.text

@pytest.mark.asyncio
async def test_email_sender_smtp_dispatch():
    settings = PlatformSettings(
        smtp_host="smtp.fake.org",
        smtp_port=587,
        smtp_user="user",
        smtp_password="pw",
        smtp_from="noreply@domain.com",
        smtp_tls=True,
    )
    sender = EmailSender(settings_provider=lambda: settings)
    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server
        await sender.send_verification_email(
            to_email="to@domain.com",
            name="Name",
            code="123456",
            link="http://link",
        )
        mock_smtp_cls.assert_called_with("smtp.fake.org", 587, timeout=10)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user", "pw")
        mock_server.send_message.assert_called_once()

@pytest.mark.asyncio
async def test_email_sender_test_connection():
    settings = PlatformSettings(
        smtp_host="smtp.fake.org",
        smtp_port=587,
        smtp_user="user",
        smtp_password="pw",
        smtp_from="noreply@domain.com",
        smtp_tls=True,
    )
    sender = EmailSender(settings_provider=lambda: settings)
    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server
        await sender.test_connection(to_email="admin@domain.com")
        mock_server.send_message.assert_called_once()
