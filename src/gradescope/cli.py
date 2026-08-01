"""CLI entry point. Subcommands land per tasks/plan.md."""

from datetime import date
from pathlib import Path

import click

from gradescope import paths, report
from gradescope.engine import EngineConfig, analyze_batch, analyze_standalone
from gradescope.validate import (
    ValidationError,
    load_batch,
    load_cost_book,
    load_inventory,
    load_probabilities,
    load_snapshots,
)
from gradescope.values import freshest_values


@click.group()
@click.version_option()
def main() -> None:
    """PSA grading decision-support: is this card worth grading?"""


@main.command()
@click.option("--card", "card_id", default=None, help="Analyze one card standalone.")
@click.option("--batch", "batch_name", default=None, help="Analyze a batch from data/batches/.")
@click.option(
    "--data-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Data directory (default: data/ if real data exists, else data/sample/).",
)
@click.option(
    "--cost-book",
    "cost_book_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Cost book YAML (default: newest in data/costs/).",
)
@click.option(
    "--scenario",
    type=click.Choice(["current", "value_restored"]),
    default="current",
    show_default=True,
    help="Pricing scenario (value_restored treats paused tiers as orderable).",
)
@click.option(
    "--as-of",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="Reference date for staleness (default: today).",
)
@click.option(
    "--membership-held/--no-membership-held",
    default=False,
    show_default=True,
    help="Whether a Collectors Club membership is already paid for.",
)
def analyze(
    card_id: str | None,
    batch_name: str | None,
    data_dir: Path | None,
    cost_book_path: Path | None,
    scenario: str,
    as_of,
    membership_held: bool,
) -> None:
    """Analyze one card standalone (--card) or a whole submission (--batch)."""
    if (card_id is None) == (batch_name is None):
        raise click.UsageError("pass exactly one of --card or --batch")
    data = data_dir or paths.default_data_dir()
    # Staleness is measured against the operator's local calendar date, which is
    # exactly date.today(); pass --as-of for reproducible runs.
    as_of_date = as_of.date() if as_of else date.today()  # noqa: DTZ011
    config = EngineConfig()
    try:
        inventory = load_inventory(data / "inventory.yaml")
        probs = load_probabilities(data / "probabilities.yaml")
        snapshots = load_snapshots(data / "values.jsonl")
        book = load_cost_book(cost_book_path or paths.newest_cost_book())

        if card_id is not None:
            if card_id not in inventory:
                raise ValidationError(
                    [
                        (
                            f"card {card_id!r} not in {data / 'inventory.yaml'} "
                            f"(known: {', '.join(sorted(inventory))})"
                        )
                    ]
                )
            if card_id not in probs:
                raise ValidationError(
                    [
                        (
                            f"card {card_id!r} has no grade probabilities in "
                            f"{data / 'probabilities.yaml'}"
                        )
                    ]
                )
            values = freshest_values(snapshots, [card_id])[card_id]
            analysis = analyze_standalone(
                card_id,
                probs[card_id],
                values,
                book,
                scenario,
                config,
                as_of_date,
                membership_already_held=membership_held,
            )
            click.echo(report.render_card_detail(analysis))
            return

        batch_path = data / "batches" / f"{batch_name}.yaml"
        if not batch_path.exists():
            raise ValidationError([f"no batch file {batch_path}"])
        batch = load_batch(batch_path, inventory)
        missing_probs = [c for c in batch.card_ids if c not in probs]
        if missing_probs:
            raise ValidationError([f"no grade probabilities for: {', '.join(missing_probs)}"])
        values_map = freshest_values(snapshots, list(batch.card_ids))
        result = analyze_batch(batch, probs, values_map, book, config, as_of_date)
        click.echo(report.render_batch(result))
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc


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
