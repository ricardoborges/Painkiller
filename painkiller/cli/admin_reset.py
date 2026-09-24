"""`painkiller admin-reset`: forget the administrator so the first access runs again."""

import asyncio
import os

import click


async def _reset(db_url: str) -> bool:
    from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker

    tracker = SQLiteIssueTracker(db_url=db_url)
    try:
        await tracker.init_db()
        settings = await tracker.get_platform_settings()
        had_admin = bool(settings.admin_username)
        settings.admin_username = None
        settings.admin_password_hash = None
        await tracker.save_platform_settings(settings)
        return had_admin
    finally:
        await tracker.close()


@click.command()
@click.option(
    "--db-url",
    default=lambda: os.environ.get("PAINKILLER_DB_URL", "sqlite+aiosqlite:///painkiller.db"),
    show_default="PAINKILLER_DB_URL",
    help="Banco da plataforma.",
)
@click.confirmation_option(prompt="Apagar o administrador? O próximo acesso à plataforma vai pedir um novo.")
def admin_reset(db_url: str):
    """Apaga usuário e senha do administrador (senha esquecida).

    O resto da configuração fica. Reinicie a API em seguida: ela guarda a conta
    em memória desde a subida. No compose:
    docker compose exec api painkiller admin-reset && docker compose restart api
    """
    had_admin = asyncio.run(_reset(db_url))
    click.echo("Administrador apagado." if had_admin else "Não havia administrador cadastrado.")
    click.echo("Reinicie a API e abra a plataforma para criar um novo no primeiro acesso.")
