"""CLI entry point. Subcommands land per tasks/plan.md."""

from pathlib import Path

import click

from gradescope import paths
from gradescope.validate import ValidationError, load_cost_book


@click.group()
@click.version_option()
def main() -> None:
    """PSA grading decision-support: is this card worth grading?"""


@main.command()
@click.option(
    "--cost-book",
    "cost_book_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Cost book YAML (default: newest in data/costs/).",
)
def costs(cost_book_path: Path | None) -> None:
    """Show the active cost book: tiers, membership, shipping, supplies, tax."""
    try:
        book = load_cost_book(cost_book_path or paths.newest_cost_book())
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Cost book: {book.path} (accessed {book.date_accessed}, {book.currency})")
    click.echo("\nService levels:")
    for lvl in book.service_levels:
        flags = []
        if lvl.status == "paused":
            flags.append("PAUSED")
        if lvl.membership_required:
            flags.append("members only")
        if lvl.min_cards:
            flags.append(f"min {lvl.min_cards} cards")
        note = f"  [{', '.join(flags)}]" if flags else ""
        lo, hi = lvl.turnaround_business_days
        click.echo(
            f"  {lvl.name:<14} ${lvl.fee_per_card:>7}/card  max DV ${lvl.max_declared_value:>6}"
            f"  ~{lo}-{hi} bd{note}"
        )
    click.echo("\nMembership:")
    for tier in book.membership:
        click.echo(f"  {tier.name:<14} ${tier.annual_fee}/yr")
    click.echo("\nReturn shipping (per submission, insured):")
    for band in book.return_shipping:
        items = f"{band.items_min}-{band.items_max}" if band.items_max else f"{band.items_min}+"
        if band.fee is not None:
            price = f"${band.fee}"
        else:
            price = f"${band.base_fee} + ${band.per_item_over}/item over {band.items_min - 1}"
        click.echo(f"  {items:>6} items, value <= ${band.value_max}: {price}")
    est = " (estimate)" if book.inbound_shipping.estimate else ""
    click.echo(f"\nInbound shipping+insurance: ${book.inbound_shipping.amount}{est}")
    click.echo(
        f"Supplies: ${book.supplies.per_card}/card + ${book.supplies.per_submission}/submission"
        + (" (estimate)" if book.supplies.estimate else "")
    )
    if book.sales_tax:
        applies = ", ".join(book.sales_tax.applies_to)
        click.echo(
            f"Sales tax ({book.sales_tax.state}): {book.sales_tax.rate * 100}% on {applies}"
            + (" (estimate)" if book.sales_tax.estimate else "")
        )
