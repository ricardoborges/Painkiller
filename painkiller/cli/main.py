"""Main CLI group for Painkiller."""

import click
from painkiller.cli.ask import ask
from painkiller.cli.agent_run import agent_run


@click.group()
def cli():
    """Painkiller Autonomous Engineering CLI."""
    pass


cli.add_command(ask)
cli.add_command(agent_run, name="agent-run")


if __name__ == "__main__":
    cli()
