"""CLI entry point. Subcommands land per tasks/plan.md."""

from collections import Counter
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import click

from gradescope import paths, report, store
from gradescope.config import load_config
from gradescope.engine import analyze_batch, analyze_standalone
from gradescope.models import (
    VARIANTS,
    Card,
    GradeProbs,
    GuidedPriorTable,
    Spread,
    ValueSnapshot,
    snapshot_kinds,
)
from gradescope.validate import (
    CARD_NUMBER_RE,
    CURRENCY_RE,
    ID_RE,
    LANGUAGE_RE,
    ValidationError,
    load_batch,
    load_cost_book,
    load_guided_priors,
    load_inventory,
    load_probabilities,
    load_snapshots,
    parse_import_csv,
    scan_snapshots,
)
from gradescope.values import freshest_values, freshest_values_partial


@click.group(invoke_without_command=True)
@click.version_option()
@click.pass_context
def main(ctx: click.Context) -> None:
    """PSA grading decision-support: is this card worth grading?

    With no subcommand, shows the values table (raw vs per-grade values and
    grading cost for every card in the inventory)."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(values)


@main.command()
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
    help="Pricing scenario for the grading-cost columns.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Config YAML overriding engine defaults (default: config.yaml at repo root).",
)
@click.option("-v", "--verbose", is_flag=True, help="Show snapshot sources and dates.")
def values(
    data_dir: Path | None,
    cost_book_path: Path | None,
    scenario: str,
    config_path: Path | None,
    verbose: bool,
) -> None:
    """Show each card's raw and per-grade values plus the cost to grade it.

    The utility view: no probabilities needed; missing snapshots show as '-'."""
    data = data_dir or paths.default_data_dir()
    try:
        config = load_config(config_path or paths.default_config())
        inventory = load_inventory(data / "inventory.yaml")
        snapshots = load_snapshots(data / "values.jsonl", config.grades)
        book = load_cost_book(cost_book_path or paths.newest_cost_book())
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    by_card = freshest_values_partial(snapshots, list(inventory), config.grades)
    click.echo(f"Inventory: {data / 'inventory.yaml'} ({len(inventory)} cards)")
    click.echo(
        report.render_values_table(inventory, by_card, book, config.grades, scenario, verbose)
    )


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
    default=None,
    help="Pricing scenario (value_restored treats paused tiers as orderable). "
    "Default: 'current' for --card; the batch file's pricing_scenario for --batch. "
    "Passing it in batch mode overrides the batch file.",
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
    help="--card mode only: membership already paid for. (Batch files carry "
    "their own membership_already_held.)",
)
@click.option(
    "--compare-scenarios",
    is_flag=True,
    default=False,
    help="Batch mode: show summary tables for both pricing scenarios side by side.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Config YAML overriding engine defaults (default: config.yaml at repo root, if present).",
)
def analyze(
    card_id: str | None,
    batch_name: str | None,
    data_dir: Path | None,
    cost_book_path: Path | None,
    scenario: str,
    as_of,
    membership_held: bool,
    compare_scenarios: bool,
    config_path: Path | None,
) -> None:
    """Analyze one card standalone (--card) or a whole submission (--batch).

    The opt-in verdict layer: EV, break-even, sensitivity, verdicts. Every
    analyzed card needs grade probabilities (gradescope add, or edit
    probabilities.yaml) and value snapshots for raw + every configured grade;
    the plain values view needs neither."""
    if (card_id is None) == (batch_name is None):
        raise click.UsageError("pass exactly one of --card or --batch")
    data = data_dir or paths.default_data_dir()
    # Staleness is measured against the operator's local calendar date, which is
    # exactly date.today(); pass --as-of for reproducible runs.
    as_of_date = as_of.date() if as_of else date.today()  # noqa: DTZ011
    try:
        config = load_config(config_path or paths.default_config())
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    try:
        inventory = load_inventory(data / "inventory.yaml")
        probs = load_probabilities(data / "probabilities.yaml", config.grades)
        snapshots = load_snapshots(data / "values.jsonl", config.grades)
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
            card_values = freshest_values(snapshots, [card_id], config.grades)[card_id]
            analysis = analyze_standalone(
                card_id,
                probs[card_id],
                card_values,
                book,
                scenario or "current",
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
        if scenario is not None:
            batch = replace(batch, pricing_scenario=scenario)
        missing_probs = [c for c in batch.card_ids if c not in probs]
        if missing_probs:
            raise ValidationError([f"no grade probabilities for: {', '.join(missing_probs)}"])
        values_map = freshest_values(snapshots, list(batch.card_ids), config.grades)
        if compare_scenarios:
            for scen in ("current", "value_restored"):
                variant = replace(batch, pricing_scenario=scen)
                result = analyze_batch(variant, probs, values_map, book, config, as_of_date)
                click.echo(report.render_batch(result, detail=False))
                click.echo()
            click.echo(
                "(value_restored is HYPOTHETICAL: Value tiers are paused for new "
                "submissions since 2026-06-02; see the cost book sources.)"
            )
            return
        result = analyze_batch(batch, probs, values_map, book, config, as_of_date)
        click.echo(report.render_batch(result))
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc


def _prompt_valid(label: str, check, error: str, default: str | None = None) -> str:
    """Prompt until `check` accepts the stripped input; explicit error each miss."""
    while True:
        kwargs = {"default": default, "show_default": bool(default)} if default is not None else {}
        text = str(click.prompt(label, **kwargs)).strip()
        if check(text):
            return text
        click.echo(f"  {error}")


def _is_iso_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _prompt_probability(label: str) -> Decimal:
    while True:
        text = str(click.prompt(label)).strip()
        try:
            value = Decimal(text)
        except InvalidOperation:
            value = None
        # NaN/Infinity parse as Decimal but poison comparisons — same rejection
        if value is None or not value.is_finite():
            click.echo(f"  {text!r} is not a number")
            continue
        if not 0 <= value <= 1:
            click.echo(f"  {value} outside [0, 1]")
            continue
        return value


def _prompt_grade_range(label: str) -> tuple[int, int] | None:
    while True:
        text = str(click.prompt(label, default="", show_default=False)).strip()
        if not text:
            return None
        parts = text.replace("-", " ").split()
        try:
            low, high = (int(p) for p in parts)
        except ValueError:
            click.echo("  want two integers like '7 9' (or blank to skip)")
            continue
        if not (1 <= low <= high <= 10):
            click.echo(f"  want 1 <= low <= high <= 10, got {low} {high}")
            continue
        return (low, high)


def _prompt_questionnaire(table: GuidedPriorTable) -> tuple[int, dict[str, str]]:
    """Walk the condition questions; returns (total points, condition fields)."""
    points = 0
    condition: dict[str, str] = {}
    click.echo("\nCondition questionnaire (drives the suggested prior):")
    for question in table.questions:
        click.echo(f"\n{question.prompt}:")
        for idx, answer in enumerate(question.answers, start=1):
            click.echo(f"  {idx}. {answer.key}")
        pick = click.prompt("Choose", type=click.IntRange(1, len(question.answers)))
        chosen = question.answers[pick - 1]
        points += chosen.points
        condition[question.field] = chosen.key
    return points, condition


def _prompt_prior(
    table: GuidedPriorTable, points: int, grades: tuple[str, ...]
) -> tuple[dict[str, Decimal], Decimal, str]:
    """Show the suggested prior; accept -> method 'guided', edit -> 'manual'.

    Either way the stored numbers are the ones the operator confirmed, and
    they must sum to 1 — re-prompted until they do, never normalized."""
    tier = table.tier_for(points)
    click.echo(f"\nCondition points: {points} -> tier '{tier.name}'. Suggested prior:")
    for grade in grades:
        click.echo(f"  PSA {grade:>4}: {tier.by_grade[grade]}")
    click.echo(f"  below {grades[0]}: {tier.p_below}")
    if click.confirm("Accept this suggested prior?", default=True):
        return dict(tier.by_grade), tier.p_below, "guided"
    while True:
        by_grade = {g: _prompt_probability(f"P(PSA {g})") for g in grades}
        p_below = _prompt_probability(f"P(below {grades[0]})")
        total = sum(by_grade.values(), p_below)
        if abs(total - 1) <= GradeProbs.TOLERANCE:
            return by_grade, p_below, "manual"
        click.echo(f"  probabilities sum to {total}, not 1 — re-enter (this tool never normalizes)")


@main.command()
@click.option(
    "--data-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Data directory to write into (default: data/ if real data exists, else data/sample/).",
)
@click.option(
    "--priors",
    "priors_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Guided-prior lookup table (default: data/guided-priors.yaml).",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Config YAML overriding engine defaults (default: config.yaml at repo root).",
)
def add(data_dir: Path | None, priors_path: Path | None, config_path: Path | None) -> None:
    """Add one card interactively: card fields, then a condition questionnaire
    that suggests a grade-probability prior from the editable lookup table
    (data/guided-priors.yaml). The stored record is always the numbers you
    confirm — accepted suggestions are recorded as method: guided, edited
    ones as method: manual. Existing ids are never overwritten without an
    explicit confirmation (and a rewrite drops YAML comments)."""
    data = data_dir or paths.default_data_dir()
    inventory_path = data / "inventory.yaml"
    probabilities_path = data / "probabilities.yaml"
    try:
        config = load_config(config_path or paths.default_config())
        table = load_guided_priors(priors_path or paths.guided_priors(), config.grades)
        inventory = load_inventory(inventory_path) if inventory_path.exists() else {}
        probabilities = (
            load_probabilities(probabilities_path, config.grades)
            if probabilities_path.exists()
            else {}
        )
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc

    overwrite = False
    while True:
        card_id = _prompt_valid(
            "Card id (lowercase slug)",
            ID_RE.match,
            "must be a lowercase slug [a-z0-9-]",
        )
        if card_id in inventory:
            if click.confirm(f"id '{card_id}' already exists in the inventory — overwrite it?"):
                overwrite = True
                break
            continue
        if card_id in probabilities:
            # orphaned probability record (id no longer in the inventory)
            if click.confirm(
                f"id '{card_id}' already has probabilities recorded — overwrite them?"
            ):
                break
            continue
        break
    name = _prompt_valid("Name", bool, "must not be empty")
    set_name = _prompt_valid("Set name", bool, "must not be empty")
    card_number = _prompt_valid(
        "Card number (e.g. 4/102, 103/99)",
        CARD_NUMBER_RE.match,
        "not a recognized card number (e.g. '4/102', '103/99')",
    )
    variant = click.prompt("Variant", type=click.Choice(sorted(VARIANTS)))
    language = _prompt_valid("Language", LANGUAGE_RE.match, "not ISO 639-1", default="en")

    points, condition = _prompt_questionnaire(table)
    notes = str(click.prompt("Condition notes (free text)", default="", show_default=False)).strip()
    if notes:
        condition["notes"] = notes
    grade_range = _prompt_grade_range("Estimated grade range 'low high' (blank to skip)")
    provenance = str(click.prompt("Provenance", default="", show_default=False)).strip()
    entry_date = date.fromisoformat(
        _prompt_valid(
            "Date",
            _is_iso_date,
            "want YYYY-MM-DD",
            default=date.today().isoformat(),  # noqa: DTZ011 — operator's calendar date
        )
    )

    by_grade, p_below, method = _prompt_prior(table, points, config.grades)

    card = Card(
        id=card_id,
        name=name,
        set_name=set_name,
        card_number=card_number,
        variant=variant,
        language=language,
        condition=condition,
        estimated_grade_range=grade_range,
        provenance=provenance,
        date_added=entry_date,
    )
    probs = GradeProbs(by_grade=by_grade, p_below=p_below, method=method, date=entry_date)

    if overwrite:
        click.echo(f"rewriting {inventory_path} (YAML comments in it are lost)")
        cards = dict(inventory)
        cards[card.id] = card
        store.rewrite_inventory(inventory_path, list(cards.values()))
    else:
        store.append_cards(inventory_path, [card])
    if card.id in probabilities:
        click.echo(f"rewriting {probabilities_path} (YAML comments in it are lost)")
        records = dict(probabilities)
        records[card.id] = probs
        store.rewrite_probabilities(probabilities_path, records)
    else:
        store.append_probability(probabilities_path, card.id, probs)
    click.echo(f"\nwrote '{card.id}' (method: {method})")
    click.echo(f"-> {inventory_path}")
    click.echo(f"-> {probabilities_path}")


@main.command("import")
@click.argument("csv_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--data-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Data directory whose inventory.yaml receives the cards "
    "(default: data/ if real data exists, else data/sample/).",
)
@click.option(
    "--strict",
    is_flag=True,
    default=False,
    help="Import nothing unless every row is valid.",
)
@click.pass_context
def import_cards(ctx: click.Context, csv_file: Path, data_dir: Path | None, strict: bool) -> None:
    """Bulk-import cards from a CSV file into the inventory (SPEC §5.6).

    The whole file is always parsed: every invalid row is reported as
    'row N, column C: message' and skipped; valid rows are appended to
    inventory.yaml. Row numbers count data rows, starting at 1 after the
    header; leading '#' lines are allowed for source citations. Exits
    nonzero if any row was rejected."""
    data = data_dir or paths.default_data_dir()
    inventory_path = data / "inventory.yaml"
    try:
        existing = load_inventory(inventory_path) if inventory_path.exists() else {}
        result = parse_import_csv(csv_file, set(existing))
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    for err in result.row_errors:
        click.echo(f"{csv_file}: {err}", err=True)
    if strict and result.rejected_rows:
        click.echo(f"--strict: {result.rejected_rows} row(s) failed validation; nothing imported")
        ctx.exit(1)
    if result.cards:
        store.append_cards(inventory_path, list(result.cards))
    click.echo(f"imported {len(result.cards)}, rejected {result.rejected_rows}")
    for set_name, count in sorted(Counter(c.set_name for c in result.cards).items()):
        click.echo(f"  {set_name}: {count}")
    if result.cards:
        click.echo(f"-> {inventory_path}")
    if result.rejected_rows:
        ctx.exit(1)


def _prompt_optional_int(label: str) -> int | None:
    while True:
        text = str(click.prompt(label, default="", show_default=False)).strip()
        if not text:
            return None
        try:
            value = int(text)
        except ValueError:
            click.echo(f"  {text!r} is not an integer (blank to skip)")
            continue
        if value < 0:
            click.echo(f"  {value} must be non-negative")
            continue
        return value


def _prompt_money(label: str, allow_blank: bool = False) -> Decimal | None:
    while True:
        kwargs = {"default": "", "show_default": False} if allow_blank else {}
        text = str(click.prompt(label, **kwargs)).strip()
        if not text and allow_blank:
            return None
        try:
            value = Decimal(text)
        except InvalidOperation:
            value = None
        # NaN/Infinity parse as Decimal but poison comparisons — same rejection
        if value is None or not value.is_finite():
            click.echo(f"  {text!r} is not a number")
            continue
        if value < 0:
            click.echo(f"  {value} must be non-negative")
            continue
        return value


@main.command()
@click.option(
    "--data-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Data directory whose values.jsonl receives the line "
    "(default: data/ if real data exists, else data/sample/).",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Config YAML overriding engine defaults (default: config.yaml at repo root).",
)
def snapshot(data_dir: Path | None, config_path: Path | None) -> None:
    """Record one value snapshot from prompts, appended to values.jsonl.

    Appends never rewrite existing lines (SPEC §5.4: the file is
    append-only history; newer snapshots supersede for analysis). Malformed
    lines already in the file are reported as warnings with their line
    numbers — fix them separately; they never block a valid append."""
    data = data_dir or paths.default_data_dir()
    values_path = data / "values.jsonl"
    inventory_path = data / "inventory.yaml"
    try:
        config = load_config(config_path or paths.default_config())
        inventory = load_inventory(inventory_path) if inventory_path.exists() else {}
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc

    while True:
        card_id = _prompt_valid(
            "Card id (lowercase slug)", ID_RE.match, "must be a lowercase slug [a-z0-9-]"
        )
        if not inventory or card_id in inventory:
            break
        if click.confirm(f"'{card_id}' is not in the inventory — record anyway?"):
            break
    kind = click.prompt("Kind", type=click.Choice(sorted(snapshot_kinds(config.grades))))
    pop_grade: str | None = None
    if kind == "pop":
        pop_grade = click.prompt("Population at grade", type=click.Choice(list(config.grades)))
        value = _prompt_money("Population count")
    else:
        value = _prompt_money("Value (gross, as the source reports it)")
    currency = _prompt_valid(
        "Currency", CURRENCY_RE.match, "must be a 3-letter uppercase code", default="USD"
    )
    source_name = _prompt_valid("Source name (e.g. 'PSA APR', 'eBay sold')", bool, "required")
    source_url = _prompt_valid("Source URL", bool, "required")
    date_observed = date.fromisoformat(
        _prompt_valid(
            "Date observed",
            _is_iso_date,
            "want YYYY-MM-DD",
            default=date.today().isoformat(),  # noqa: DTZ011 — operator's calendar date
        )
    )
    n_comps = _prompt_optional_int("Number of comps (blank to skip)")
    spread = None
    low = _prompt_money("Spread low (blank to skip)", allow_blank=True)
    if low is not None:
        while True:
            high = _prompt_money(f"Spread high (>= {low})")
            if high >= low:
                break
            click.echo(f"  high {high} < low {low}")
        spread = Spread(low=low, high=high)
    recorded_by = str(click.prompt("Recorded by", default="manual-entry")).strip()

    snap = ValueSnapshot(
        card_id=card_id,
        kind=kind,
        value=value,
        currency=currency,
        source_name=source_name,
        source_url=source_url,
        date_observed=date_observed,
        n_comps=n_comps,
        spread=spread,
        recorded_by=recorded_by,
        pop_grade=pop_grade,
    )
    if values_path.exists():
        _, problems = scan_snapshots(values_path, config.grades)
        for problem in problems:
            click.echo(f"warning: {problem}", err=True)
        if problems:
            click.echo(
                f"warning: {len(problems)} existing line(s) are malformed — appends never "
                "rewrite them; fix by hand and re-check with validate-snapshots",
                err=True,
            )
    store.append_snapshot(values_path, snap)
    click.echo(f"appended {kind} snapshot for '{card_id}' -> {values_path}")


@main.command("validate-snapshots")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Config YAML overriding engine defaults (default: config.yaml at repo root).",
)
@click.pass_context
def validate_snapshots(ctx: click.Context, file: Path, config_path: Path | None) -> None:
    """Lint any snapshot file: JSONL shape, schema, kinds vs the configured
    grade set, dates, currency, pop_grade for pop lines.

    Every problem is reported with its line number; a clean file exits 0.
    This is the deterministic gate for hand- or AI-written snapshot files
    (SPEC §7): nothing enters analysis without passing it."""
    try:
        config = load_config(config_path or paths.default_config())
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    snaps, errors = scan_snapshots(file, config.grades)
    for err in errors:
        click.echo(err, err=True)
    if errors:
        click.echo(f"{file}: {len(errors)} problem(s), {len(snaps)} valid line(s)")
        ctx.exit(1)
    click.echo(f"OK: {file}: {len(snaps)} snapshot line(s), no problems")


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
