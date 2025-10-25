"""CLI interface for scan2wall package.

Usage:
    scan2wall              # Show version and basic info
    scan2wall test full    # Test full pipeline on images in /totry
"""

import click
from scan2wall import __version__


@click.group()
@click.version_option(version=__version__, prog_name="scan2wall")
def main():
    """scan2wall - AI pipeline for 2D photos to 3D physics simulations."""
    pass


@main.command()
def info():
    """Show version and basic information."""
    print(f"scan2wall v{__version__}")
    print("Scan objects and simulate throwing them at a wall using AI and physics.")
    print("")
    print("Quick start:")
    print("  ./start.sh auto")
    print("")
    print("Available commands:")
    print("  scan2wall test       # Run pipeline tests")
    print("  scan2wall --help     # Show all commands")


# Import test commands
from scan2wall.cli.test import test
main.add_command(test)


# Default behavior: show info if no command given
@main.result_callback()
@click.pass_context
def default_command(ctx, result, **kwargs):
    """Show info if no subcommand was invoked."""
    if ctx.invoked_subcommand is None:
        info()


if __name__ == "__main__":
    main()
