"""CLI entry point. Subcommands land per tasks/plan.md."""

import click


@click.group()
@click.version_option()
def main() -> None:
    """PSA grading decision-support: is this card worth grading?"""
