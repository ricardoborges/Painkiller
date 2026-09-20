"""Main CLI group for Painkiller."""

import click
from painkiller.cli.ask import ask


@click.group()
def cli():
    """Painkiller Autonomous Engineering CLI."""
    pass


cli.add_command(ask)


if __name__ == "__main__":
    cli()
