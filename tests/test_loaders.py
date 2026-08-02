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
