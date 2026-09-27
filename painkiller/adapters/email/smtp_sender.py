"""SMTP email sender adapter with local console fallback."""

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Callable, Optional

from painkiller.core.domain.models import PlatformSettings

logger = logging.getLogger(__name__)


class EmailSender:
    """Sends verification and transactional emails using configured SMTP or console fallback."""

    def __init__(self, settings_provider: Callable[[], PlatformSettings]):
        self._settings_provider = settings_provider

    @property
    def settings(self) -> PlatformSettings:
        return self._settings_provider()

    async def send_verification_email(self, to_email: str, name: str, code: str, link: str) -> None:
        """Send verification code and activation link to a newly registered user."""
        settings = self.settings
        subject = "Confirme sua conta no Painkiller / Verify your Painkiller account"

        text_body = (
            f"Olá {name},\n\n"
            f"Seu código de confirmação para ativar sua conta no Painkiller é:\n\n"
            f"    {code}\n\n"
            f"Ou se preferir, clique no link abaixo para ativar sua conta diretamente:\n\n"
            f"    {link}\n\n"
            f"Este código e link expiram em 24 horas.\n"
        )

        html_body = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 560px; margin: 0 auto; padding: 24px; color: #111;">
            <h2 style="margin-top: 0;">Bem-vindo ao Painkiller!</h2>
            <p>Olá <strong>{name}</strong>,</p>
            <p>Use o código de 6 dígitos abaixo para ativar sua conta:</p>
            <div style="background: #f4f4f5; padding: 16px; border-radius: 8px; font-size: 28px; font-weight: bold; letter-spacing: 4px; text-align: center; margin: 20px 0;">
                {code}
            </div>
            <p>Ou clique no botão abaixo para ativar sua conta diretamente:</p>
            <p style="text-align: center; margin: 24px 0;">
                <a href="{link}" style="background: #000; color: #fff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 500; display: inline-block;">
                    Ativar minha conta
                </a>
            </p>
            <p style="font-size: 13px; color: #666; margin-top: 32px; border-top: 1px solid #e4e4e7; padding-top: 16px;">
                Se você não solicitou este cadastro, pode ignorar esta mensagem.
            </p>
        </div>
        """

        if not settings.smtp_host:
            self._log_simulation(to_email, subject, code, link)
            return

        await asyncio.to_thread(self._dispatch_smtp, to_email, subject, text_body, html_body)

    async def test_connection(self, to_email: str) -> None:
        """Send a test email to verify SMTP configuration."""
        subject = "Teste de configuração SMTP — Painkiller"
        text_body = "Se você recebeu este e-mail, as configurações de SMTP do Painkiller estão funcionando perfeitamente!"
        html_body = "<p>Se você recebeu este e-mail, as configurações de SMTP do <strong>Painkiller</strong> estão funcionando perfeitamente!</p>"

        settings = self.settings
        if not settings.smtp_host:
            raise ValueError("Servidor SMTP não configurado.")

        await asyncio.to_thread(self._dispatch_smtp, to_email, subject, text_body, html_body)

    def _log_simulation(self, to_email: str, subject: str, code: str, link: str) -> None:
        logger.info(
            "\n" + "=" * 70 + "\n"
            f"[EMAIL DISPATCH - LOCAL DEV MODE]\n"
            f"Para / To: {to_email}\n"
            f"Assunto / Subject: {subject}\n"
            f"Código / Code: {code}\n"
            f"Link: {link}\n" + "=" * 70
        )

    def _dispatch_smtp(self, to_email: str, subject: str, text_body: str, html_body: Optional[str] = None) -> None:
        settings = self.settings
        port = settings.smtp_port or 587
        host = settings.smtp_host or ""
        sender = settings.smtp_from or (settings.smtp_user if settings.smtp_user and "@" in settings.smtp_user else "noreply@painkiller.local")

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_email
        msg.set_content(text_body)

        if html_body:
            msg.add_alternative(html_body, subtype="html")

        if port == 465:
            server_cls = smtplib.SMTP_SSL
        else:
            server_cls = smtplib.SMTP

        with server_cls(host, port, timeout=10) as server:
            if port != 465 and settings.smtp_tls:
                server.starttls()
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
