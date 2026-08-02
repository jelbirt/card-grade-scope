"""Golden EV cases with hand-computed expected values (SPEC §9).

Grade set: the default 7.5/8/8.5/9/10; sale_friction 0 (sticker is the only
view). All cases pin to the frozen fixture cost book and the committed sample
collection, with exact Decimal equality — any drift fails these tests.
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
CONFIG = EngineConfig()  # SPEC §12 defaults: friction 0, alpha 1.0, min_gain 20


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
    """Hand computation (current scenario, batch of one, friction 0).

    Gross values: raw 90; 7.5: 120, 8: 160, 8.5: 200, 9: 260, 10: 750.
    Probs: .10 / .25 / .15 / .25 / .20, below .05; alpha = 1.

    declared value = .10x120 + .25x160 + .15x200 + .25x260 + .20x750 + .05x90
                   = 12 + 40 + 30 + 65 + 150 + 4.50 = 301.50 -> tier regular

    Costs: fee 79.99; CT tax 79.99 x .0635 = 5.079365; card supplies 0.30
      shared (solo): inbound 25.00 + return band 1-4/<=2000 19.99 + packing 8.00
                   = 52.99
      C_i = 79.99 + 5.079365 + 0.30 + 52.99 = 138.359365

    EV(graded) = 301.50 (same weighted sum as DV since alpha = 1)
    EV(submit) = 301.50 - 138.359365 = 163.140635
    Net gain   = 163.140635 - 90 = 73.140635 -> base rule submit (>= 20)

    Sensitivity: -25% graded shock: 297 x 0.75 + 4.50 = 227.25
                 gain = 227.25 - 138.359365 - 90 = -1.109365 <= 0
    -> final verdict HOLD (not robust); flips only at the 25% shock, so the
    robustness label is 'sensitive', not 'fragile'.
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
    assert a.declared_value == Decimal("301.50")
    assert a.cost.tier.name == "regular"
    assert a.cost.tax_on_fee == Decimal("5.079365")
    assert a.cost.total == Decimal("138.359365")
    assert a.sticker.ev_graded == Decimal("301.50")
    assert a.sticker.ev_submit == Decimal("163.140635")
    assert a.sticker.net_gain == Decimal("73.140635")
    assert a.sticker.base_verdict == "submit"
    assert a.sticker.verdict == "hold"
    assert "not robust" in a.sticker.reason
    assert a.sticker.sensitivity.robustness == "sensitive"
    assert a.sticker.sensitivity.min_gain_under_value_shocks == Decimal("-1.109365")
    assert a.take_home is None  # friction 0: sticker is the only view
    assert a.overall_verdict == "hold"
    assert not a.upcharge_risk  # 750 <= 1500
    assert not a.stale_kinds


def test_golden_mewtwo_breakeven(book, sample_values, sample_probs):
    """Break-even (sticker, solo):
    A = non-top EV / (1 - p10) = (12 + 40 + 30 + 65 + 4.50) / 0.80
      = 151.50 / 0.80 = 189.375
    t* = (C + raw - A) / (V10 - A) = (138.359365 + 90 - 189.375) / (750 - 189.375)
       = 38.984365 / 560.625 = 0.0695373...  -> 0.069537 at 1e-6
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
    be = a.sticker.breakeven
    assert be.kind == "threshold"
    assert be.p_top_min.quantize(Decimal("1e-6")) == Decimal("0.069537")


def test_golden_deerling_never_viable(book, sample_values, sample_probs):
    """Deerling common: PSA 10 (35.00) is far below the ~138 cost.

    declared value = .10x4 + .30x8 + .25x11 + .25x15 + .05x35 + .05x0.25
                   = 0.40 + 2.40 + 2.75 + 3.75 + 1.75 + 0.0125 = 11.0625
    Cost floor triggers -> DON'T BOTHER; break-even 'never'.
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
    assert a.declared_value == Decimal("11.0625")
    assert a.cost.total == Decimal("138.359365")
    assert a.sticker.verdict == "dont_bother"
    assert "cost floor" in a.sticker.reason
    assert a.sticker.breakeven.kind == "never"
    assert a.overall_verdict == "dont_bother"


def test_golden_short_circuit_below():
    """p_below = 0.60 >= 0.5 short-circuits to don't bother regardless of
    values (SPEC §6). Probabilities constructed inline."""
    probs = GradeProbs(
        by_grade={
            "7.5": Decimal("0.20"),
            "8": Decimal("0.10"),
            "8.5": Decimal("0.03"),
            "9": Decimal("0.05"),
            "10": Decimal("0.02"),
        },
        p_below=Decimal("0.60"),
    )
    snaps = load_snapshots(SAMPLE / "values.jsonl")
    values_map = freshest_values(snaps, ["nd-54-mewtwo-ex-full-art"])
    values = CardValues(
        card_id="hypothetical",
        grades=CONFIG.grades,
        by_kind=values_map["nd-54-mewtwo-ex-full-art"].by_kind,
    )
    book = load_cost_book(FROZEN_BOOK)
    a = analyze_standalone("hypothetical", probs, values, book, "current", CONFIG, AS_OF)
    assert a.short_circuited
    assert a.sticker.verdict == "dont_bother"
    assert "expected grade below 7.5" in a.sticker.reason
    assert a.overall_verdict == "dont_bother"


def test_golden_value_restored_scenario_zoroark(book, sample_values, sample_probs):
    """Zoroark holo under value_restored, standalone: value_bulk is blocked by
    its 20-card minimum at n=1, so the cheapest eligible is value (32.99).

    declared value = .15x6 + .30x14 + .25x20 + .20x28 + .05x80 + .05x4
                   = 0.90 + 4.20 + 5.00 + 5.60 + 4.00 + 0.20 = 19.90
    Still don't bother standalone; the batch math is where bulk pricing helps.
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
    assert a.declared_value == Decimal("19.90")
    assert a.overall_verdict == "dont_bother"
