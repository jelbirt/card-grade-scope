from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner

from gradescope import paths
from gradescope.cli import main
from gradescope.validate import (
    ValidationError,
    load_batch,
    load_cost_book,
    load_inventory,
    load_probabilities,
    load_snapshots,
)

SAMPLE = paths.repo_root() / "data" / "sample"
COSTS = paths.repo_root() / "data" / "costs" / "psa-costs-2026-08-01.yaml"


# ------------------------------------------------------------- happy paths


def test_sample_inventory_loads():
    cards = load_inventory(SAMPLE / "inventory.yaml")
    assert len(cards) == 6
    secret = cards["de-111-pokemon-catcher-secret"]
    assert secret.card_number == "111/108"  # secret-rare numbering above set size
    assert secret.variant == "secret_rare"


def test_sample_probabilities_load_and_are_decimal():
    probs = load_probabilities(SAMPLE / "probabilities.yaml")
    assert set(probs) >= {"nd-54-mewtwo-ex-full-art", "nd-1-deerling-common"}
    mewtwo = probs["nd-54-mewtwo-ex-full-art"]
    assert isinstance(mewtwo.p("10"), Decimal)
    assert mewtwo.p("7.5") == Decimal("0.10")  # YAML keys canonicalized to labels
    assert mewtwo.total == Decimal(1)


def test_sample_snapshots_load():
    snaps = load_snapshots(SAMPLE / "values.jsonl")
    kinds = {(s.card_id, s.kind) for s in snaps}
    assert ("nd-54-mewtwo-ex-full-art", "psa10") in kinds
    assert ("nd-54-mewtwo-ex-full-art", "psa7.5") in kinds  # half-grade kind
    pop = [s for s in snaps if s.kind == "pop"]
    assert pop and pop[0].pop_grade == "10"
    ten = next(s for s in snaps if s.card_id == "nd-54-mewtwo-ex-full-art" and s.kind == "psa10")
    assert ten.value == Decimal("750.00")


def test_cost_book_loads_with_decimals_and_paused_tiers():
    book = load_cost_book(COSTS)
    regular = book.level("regular")
    assert regular.fee_per_card == Decimal("79.99")
    assert regular.status == "active"
    bulk = book.level("value_bulk")
    assert bulk.status == "paused"
    assert bulk.min_cards == 20 and bulk.membership_required
    # scenario filtering
    assert {level.name for level in book.orderable_levels("current")} == {
        "regular",
        "express",
        "super_express",
        "walk_through",
    }
    assert len(book.orderable_levels("value_restored")) == 8
    assert book.sales_tax is not None and book.sales_tax.rate == Decimal("0.0635")


def test_sample_batch_loads():
    inventory = load_inventory(SAMPLE / "inventory.yaml")
    batch = load_batch(SAMPLE / "batches" / "demo.yaml", inventory)
    assert batch.pricing_scenario == "current"
    assert len(batch.card_ids) == 6


def test_costs_cli_renders():
    result = CliRunner().invoke(main, ["costs", "--cost-book", str(COSTS)])
    assert result.exit_code == 0, result.output
    assert "regular" in result.output
    assert "PAUSED" in result.output
    assert "6.35" in result.output


# ------------------------------------------------------------ rejections


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_probability_sum_rejected_loudly(tmp_path):
    p = _write(
        tmp_path,
        "probs.yaml",
        """
some-card:
  grades:
    "7.5": 0.50
    "8": 0.20
    "8.5": 0.10
    "9": 0.10
    "10": 0.05
  below: 0.10
""",
    )
    with pytest.raises(ValidationError) as exc:
        load_probabilities(p)
    assert "sum to 1.05" in str(exc.value)
    assert "never silently normalizes" in str(exc.value)


def test_probability_unknown_and_missing_grades_rejected(tmp_path):
    p = _write(
        tmp_path,
        "probs.yaml",
        """
some-card:
  grades:
    "7": 0.50
    "8": 0.50
  below: 0
""",
    )
    with pytest.raises(ValidationError) as exc:
        load_probabilities(p)
    msg = str(exc.value)
    assert "grade '7' is not in the configured grade set" in msg
    assert "missing probability for grade(s)" in msg


def test_duplicate_and_bad_ids_rejected(tmp_path):
    p = _write(
        tmp_path,
        "inv.yaml",
        """
- id: ok-card
  name: A
  set_name: S
  card_number: "1/99"
  variant: unlimited
- id: ok-card
  name: B
  set_name: S
  card_number: "2/99"
  variant: unlimited
- id: Bad_ID
  name: C
  set_name: S
  card_number: "3/99"
  variant: nonsense
""",
    )
    with pytest.raises(ValidationError) as exc:
        load_inventory(p)
    msg = str(exc.value)
    assert "duplicate card id" in msg
    assert "lowercase slug" in msg
    assert "unknown variant" in msg


def test_snapshot_rejections(tmp_path):
    p = _write(
        tmp_path,
        "values.jsonl",
        '{"card_id": "x", "kind": "psa11", "value": 1, "currency": "USD", '
        '"source_name": "s", "source_url": "u", "date_observed": "2026-01-01"}\n'
        '{"card_id": "x", "kind": "pop", "value": 5, "currency": "USD", '
        '"source_name": "s", "source_url": "u", "date_observed": "2026-01-01"}\n',
    )
    with pytest.raises(ValidationError) as exc:
        load_snapshots(p)
    msg = str(exc.value)
    assert "line 1" in msg and "unknown kind" in msg
    assert "line 2" in msg and "pop_grade" in msg


def test_values_cli_renders_table():
    result = CliRunner().invoke(main, ["values", "--cost-book", str(COSTS)])
    assert result.exit_code == 0, result.output
    assert "PSA 7.5" in result.output and "PSA 10" in result.output
    assert "nd-54-mewtwo-ex-full-art" in result.output
    assert "$750.00" in result.output
    assert "all-in/card" in result.output


def test_values_table_shows_per_grade_profit_line():
    """SPEC per-grade profit/loss line (2026-08-02): V_g - V_raw - all-in/card,
    shown under each value row; the gross value cells stay untouched.

    Hand-computed for the Mewtwo fixture: all-in = 79.99 * 1.0635 + 0.30
    = 85.369365. PSA 10: 750 - 90 - 85.369365 = +574.630635 -> +$574.63.
    PSA 7.5: 120 - 90 - 85.369365 = -55.369365 -> -$55.37."""
    result = CliRunner().invoke(main, ["values", "--cost-book", str(COSTS)])
    assert result.exit_code == 0, result.output
    assert "profit/loss if graded" in result.output
    assert "+$574.63" in result.output
    assert "-$55.37" in result.output
    # deerling common: PSA 10 is 35 - 0.25 - 85.369365 -> a loss even at a 10
    assert "-$50.62" in result.output
    # the gross value cells are still there, not replaced
    assert "$750.00" in result.output and "$120.00" in result.output
    # legend states the arithmetic and the before-fees stance
    assert "before any seller fees" in result.output


def test_bare_invocation_shows_values_table():
    result = CliRunner().invoke(main, [])
    assert result.exit_code == 0, result.output
    assert "PSA 7.5" in result.output


def test_batch_unknown_card_rejected(tmp_path):
    inventory = load_inventory(SAMPLE / "inventory.yaml")
    p = _write(
        tmp_path,
        "batch.yaml",
        """
name: bad
pricing_scenario: current
card_ids: [nope-not-real]
""",
    )
    with pytest.raises(ValidationError) as exc:
        load_batch(p, inventory)
    assert "unknown card id 'nope-not-real'" in str(exc.value)


def test_values_profit_line_edge_cases():
    """Review pass: the profit line must be cleanly omitted when it cannot be
    computed, while the gross row still renders with '-' cells."""
    from datetime import date as date_cls
    from decimal import Decimal

    from gradescope.models import DEFAULT_GRADES, Card, ValueSnapshot
    from gradescope.report import money_signed, render_values_table
    from gradescope.validate import load_cost_book

    book = load_cost_book(COSTS)

    def snap(kind, value):
        return ValueSnapshot(
            card_id="c",
            kind=kind,
            value=Decimal(value),
            currency="USD",
            source_name="s",
            source_url="u",
            date_observed=date_cls(2026, 7, 1),
        )

    card = {"c": Card(id="c", name="X", set_name="S", card_number="1/99", variant="unlimited")}
    full = {f"psa{g}": snap(f"psa{g}", "50") for g in DEFAULT_GRADES}

    # no raw snapshot -> no profit line, gross cells intact
    out = render_values_table(card, {"c": dict(full)}, book, DEFAULT_GRADES)
    assert "profit/loss if graded =" in out  # legend
    assert "  profit/loss if graded  " not in out  # but no per-card line
    assert "$50.00" in out

    # no top-grade snapshot -> no tier, no all-in, no profit line
    partial = {"raw": snap("raw", "10"), "psa8": snap("psa8", "50")}
    out = render_values_table(card, {"c": partial}, book, DEFAULT_GRADES)
    assert "  profit/loss if graded  " not in out

    # top-grade value beyond every orderable tier -> no costable tier, no line
    rich = {"raw": snap("raw", "10"), **full, "psa10": snap("psa10", "999999")}
    out = render_values_table(card, {"c": rich}, book, DEFAULT_GRADES)
    assert "  profit/loss if graded  " not in out

    # empty snaps -> all '-' cells, no crash
    out = render_values_table(card, {"c": {}}, book, DEFAULT_GRADES)
    assert "  profit/loss if graded  " not in out

    # sub-cent loss rounds to a signed zero with a plus sign
    assert money_signed(Decimal("-0.001")) == "+$0.00"
    assert money_signed(Decimal("-0.005001")) == "-$0.01"
