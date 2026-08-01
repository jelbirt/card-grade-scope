"""Golden EV cases with hand-computed expected values (SPEC §9).

All cases pin to the frozen fixture cost book in tests/golden/fixtures/ and the
committed sample collection, with exact Decimal equality — any drift in the
engine's arithmetic fails these tests.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from gradescope import paths
from gradescope.engine import EngineConfig, analyze_standalone
from gradescope.models import GradeProbs
from gradescope.validate import load_cost_book, load_probabilities, load_snapshots
from gradescope.values import CardValues, freshest_values

SAMPLE = paths.repo_root() / "data" / "sample"
FROZEN_BOOK = Path(__file__).parent / "fixtures" / "cost-book-frozen.yaml"
AS_OF = date(2026, 8, 1)
CONFIG = EngineConfig()  # SPEC §12 defaults: friction 0.13, alpha 1.0, min_gain 20


@pytest.fixture(scope="module")
def book():
    return load_cost_book(FROZEN_BOOK)


@pytest.fixture(scope="module")
def sample_values():
    snaps = load_snapshots(SAMPLE / "values.jsonl")
    ids = [
        "nd-54-mewtwo-ex-full-art",
        "nd-1-deerling-common",
        "de-46-zoroark-holo",
    ]
    return freshest_values(snaps, ids)


@pytest.fixture(scope="module")
def sample_probs():
    return load_probabilities(SAMPLE / "probabilities.yaml")


def test_golden_mewtwo_standalone_current(book, sample_values, sample_probs):
    """Hand computation (sticker view, current scenario, batch of one).

    Gross values: raw 90, psa7 110, psa8 160, psa9 260, psa10 750.
    Probs: p7 .10, p8 .35, p9 .40, p10 .10, below7 .05; alpha = 1.

    declared value = .10x110 + .35x160 + .40x260 + .10x750 + .05x(1x90)
                   = 11 + 56 + 104 + 75 + 4.50 = 250.50 -> tier regular (79.99)

    Costs: fee 79.99; CT tax 79.99 x .0635 = 5.079365; card supplies 0.30
      shared (solo): inbound 25.00 + return band 1-4/<=2000 19.99 + packing 8.00
                   = 52.99
      C_i = 79.99 + 5.079365 + 0.30 + 52.99 = 138.359365

    Sticker: EV(graded) = 246 + 4.50 = 250.50
             EV(submit) = 250.50 - 138.359365 = 112.140635
             Net gain   = 112.140635 - 90 = 22.140635  -> submit (>= 20)

    Take-home (x 0.87): EV(graded) = 250.50 x 0.87 = 217.935
             EV(submit) = 217.935 - 138.359365 = 79.575635
             Net gain   = 79.575635 - 90 x 0.87 (=78.30) = 1.275635 -> hold

    Views disagree -> overall HOLD.
    """
    a = analyze_standalone(
        "nd-54-mewtwo-ex-full-art",
        sample_probs["nd-54-mewtwo-ex-full-art"],
        sample_values["nd-54-mewtwo-ex-full-art"],
        book,
        "current",
        CONFIG,
        AS_OF,
    )
    assert a.declared_value == Decimal("250.50")
    assert a.cost.tier.name == "regular"
    assert a.cost.tax_on_fee == Decimal("5.079365")
    assert a.cost.total == Decimal("138.359365")
    assert a.sticker.ev_graded == Decimal("250.50")
    assert a.sticker.ev_submit == Decimal("112.140635")
    assert a.sticker.net_gain == Decimal("22.140635")
    assert a.sticker.verdict == "submit"
    assert a.take_home.ev_graded == Decimal("217.9350")
    assert a.take_home.net_gain == Decimal("1.275635")
    assert a.take_home.verdict == "hold"
    assert a.overall_verdict == "hold"
    assert "views disagree" in a.overall_reason
    assert not a.upcharge_risk  # 750 <= 1500
    assert not a.stale_kinds  # observed 2026-07-20, as-of 2026-08-01, threshold 90d


def test_golden_deerling_never_viable(book, sample_values, sample_probs):
    """Deerling common: PSA 10 (35.00 sticker) is far below the ~138 cost.

    declared value = .15x5 + .40x8 + .35x15 + .05x35 + .05x(1x0.25)
                   = 0.75 + 3.20 + 5.25 + 1.75 + 0.0125 = 10.9625 -> regular
    Cost floor triggers in both views -> DON'T BOTHER overall.
    """
    a = analyze_standalone(
        "nd-1-deerling-common",
        sample_probs["nd-1-deerling-common"],
        sample_values["nd-1-deerling-common"],
        book,
        "current",
        CONFIG,
        AS_OF,
    )
    assert a.declared_value == Decimal("10.9625")
    assert a.cost.total == Decimal("138.359365")
    assert a.sticker.verdict == "dont_bother"
    assert "cost floor" in a.sticker.reason
    assert a.take_home.verdict == "dont_bother"
    assert a.overall_verdict == "dont_bother"


def test_golden_short_circuit_below7():
    """p_below7 = 0.60 >= 0.5 short-circuits to don't bother in every view,
    regardless of values (SPEC §6). Values constructed inline."""
    probs = GradeProbs(
        p7=Decimal("0.20"),
        p8=Decimal("0.10"),
        p9=Decimal("0.05"),
        p10=Decimal("0.05"),
        p_below7=Decimal("0.60"),
    )
    snaps = load_snapshots(SAMPLE / "values.jsonl")
    values_map = freshest_values(snaps, ["nd-54-mewtwo-ex-full-art"])
    values = CardValues(
        card_id="hypothetical", by_kind=values_map["nd-54-mewtwo-ex-full-art"].by_kind
    )
    book = load_cost_book(FROZEN_BOOK)
    a = analyze_standalone("hypothetical", probs, values, book, "current", CONFIG, AS_OF)
    assert a.short_circuited
    assert a.sticker.verdict == "dont_bother"
    assert a.take_home.verdict == "dont_bother"
    assert (
        "expected grade below 7" in a.overall_reason or "expected grade below 7" in a.sticker.reason
    )
    assert a.overall_verdict == "dont_bother"


def test_golden_value_restored_scenario_flips_zoroark(book, sample_values, sample_probs):
    """Zoroark holo (raw 4.00): dead at $79.99 Regular, but under value_restored
    a batch of 20+ could use value_bulk at 24.99. Standalone (n=1) still cannot
    use value_bulk (20-card minimum) — the cheapest eligible is value (32.99).

    declared value = .20x8 + .40x14 + .30x28 + .05x80 + .05x(1x4)
                   = 1.60 + 5.60 + 8.40 + 4.00 + 0.20 = 19.80 -> value tier (32.99)
    Cost: 32.99 + tax 2.094865 + 0.30 + 52.99 = 88.374865
    Sticker EV(graded) = 19.80; net gain = 19.80 - 88.374865 - 4 = way negative.
    Still don't bother standalone — the flip Jake cares about needs the batch
    math (Task 4); this pins tier eligibility + min-card enforcement.
    """
    a = analyze_standalone(
        "de-46-zoroark-holo",
        sample_probs["de-46-zoroark-holo"],
        sample_values["de-46-zoroark-holo"],
        book,
        "value_restored",
        CONFIG,
        AS_OF,
    )
    assert a.cost.tier.name == "value"  # not value_bulk: 20-card minimum, n=1
    assert a.cost.grading_fee == Decimal("32.99")
    assert a.declared_value == Decimal("19.80")
    assert a.overall_verdict == "dont_bother"
