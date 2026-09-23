"""Main CLI group for Painkiller."""

import click
from painkiller.cli.ask import ask
from painkiller.cli.agent_run import agent_run
from painkiller.cli.acp_run import acp_run
from painkiller.cli.unreal_run import unreal_run


@click.group()
def cli():
    """Painkiller Autonomous Engineering CLI."""
    pass


cli.add_command(ask)
cli.add_command(agent_run, name="agent-run")
cli.add_command(acp_run, name="acp-run")
cli.add_command(unreal_run, name="unreal-run")


if __name__ == "__main__":
    cli()
