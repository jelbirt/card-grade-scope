"""Sensitivity grid, flip points, and the final verdict rules (SPEC §6)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from gradescope.engine import EngineConfig, analyze_standalone
from gradescope.models import (
    CostBook,
    CostLine,
    GradeProbs,
    ReturnShippingBand,
    ServiceLevel,
    Source,
    Supplies,
    ValueSnapshot,
)
from gradescope.validate import load_cost_book
from gradescope.values import CardValues

FROZEN_BOOK = Path(__file__).parent / "golden" / "fixtures" / "cost-book-frozen.yaml"
AS_OF = date(2026, 8, 1)
CONFIG = EngineConfig()
GRADES = CONFIG.grades

SRC = Source(url="https://example.com/fixture", date_accessed=date(2026, 8, 1))


def _snap(card_id: str, kind: str, value: str, observed: date) -> ValueSnapshot:
    return ValueSnapshot(
        card_id=card_id,
        kind=kind,
        value=Decimal(value),
        currency="USD",
        source_name="FIXTURE",
        source_url="https://example.com/fixture",
        date_observed=observed,
    )


def _values(card_id: str, raw: str, by_grade: dict[str, str], observed=date(2026, 7, 20)):
    by_kind = {"raw": _snap(card_id, "raw", raw, observed)}
    for g, v in by_grade.items():
        by_kind[f"psa{g}"] = _snap(card_id, f"psa{g}", v, observed)
    return CardValues(card_id=card_id, grades=GRADES, by_kind=by_kind)


def _flat_book(fee: str) -> CostBook:
    """Tiny inline book: one tier, no tax, no membership, zero shared costs."""
    return CostBook(
        date_accessed=date(2026, 8, 1),
        currency="USD",
        service_levels=(
            ServiceLevel(
                name="flat",
                status="active",
                fee_per_card=Decimal(fee),
                max_declared_value=Decimal(100000),
                turnaround_business_days=(10, 20),
                source=SRC,
            ),
        ),
        membership=(),
        return_shipping=(
            ReturnShippingBand(
                items_min=1,
                items_max=None,
                value_max=Decimal(1000000),
                source=SRC,
                fee=Decimal(0),
            ),
        ),
        inbound_shipping=CostLine(amount=Decimal(0), source=SRC),
        supplies=Supplies(per_card=Decimal(0), per_submission=Decimal(0), source=SRC),
        sales_tax=None,
    )


ROBUST_PROBS = GradeProbs(
    by_grade={
        "7.5": Decimal("0.10"),
        "8": Decimal("0.10"),
        "8.5": Decimal("0.20"),
        "9": Decimal("0.40"),
        "10": Decimal("0.15"),
    },
    p_below=Decimal("0.05"),
)
ROBUST_VALUES = {"7.5": "350", "8": "400", "8.5": "600", "9": "900", "10": "2000"}


@pytest.fixture(scope="module")
def frozen_book():
    return load_cost_book(FROZEN_BOOK)


def test_robust_submit_survives(frozen_book):
    """A high-margin card survives every shock: base submit stands.

    raw 100; EV = .10x350 + .10x400 + .20x600 + .40x900 + .15x2000 + .05x100
                = 35 + 40 + 120 + 360 + 300 + 5 = 860 -> regular (DV 860)
    gain = 860 - 138.359365 - 100 = 621.640635; -25% graded swing 213.75
    -> min gain > 0 everywhere, no verdict flips."""
    a = analyze_standalone(
        "robust-card",
        ROBUST_PROBS,
        _values("robust-card", "100", ROBUST_VALUES),
        frozen_book,
        "current",
        CONFIG,
        AS_OF,
    )
    assert a.sticker.base_verdict == "submit"
    assert a.sticker.verdict == "submit"
    assert a.sticker.net_gain == Decimal("621.640635")
    assert a.sticker.sensitivity.robustness == "robust"
    assert not a.sticker.sensitivity.flips
    assert a.take_home is None  # friction 0 default
    assert a.overall_verdict == "submit"
    assert a.upcharge_risk  # psa10 2000 > regular max 1500 -> warned


def test_stale_snapshots_downgrade_submit_to_hold(frozen_book):
    """Same robust card, but snapshots observed 200 days before as-of:
    submit -> hold with the stale reason naming the threshold."""
    values = _values("stale-card", "100", ROBUST_VALUES, observed=date(2026, 1, 13))
    a = analyze_standalone(
        "stale-card", ROBUST_PROBS, values, frozen_book, "current", CONFIG, AS_OF
    )
    assert a.stale_kinds == ["raw", "psa7.5", "psa8", "psa8.5", "psa9", "psa10"]
    assert a.sticker.base_verdict == "submit"
    assert a.sticker.verdict == "hold"
    assert "stale snapshots" in a.sticker.reason
    assert a.overall_verdict == "hold"


def test_views_disagree_yields_overall_hold_when_friction_configured():
    """With sale_friction 0.1325 configured, a card can be a robust sticker
    submit but a thin take-home hold -> overall HOLD (views disagree).

    Values 60/80/90/100/150, raw 5, probs .20/.30/.25/.15/.05, below .05.
    Sticker: EV = 12 + 24 + 22.5 + 15 + 7.5 + 0.25 = 81.25; C = 50
             gain = 81.25 - 50 - 5 = 26.25 -> submit
             -25% graded: 81 x 0.75 + 0.25 = 61.00 -> gain 6.00 > 0 (keeps submit)
    Take-home (x 0.8675): EV = 70.484375; raw 4.3375
             gain = 70.484375 - 50 - 4.3375 = 16.146875 -> hold (< 20)
    """
    config = EngineConfig(sale_friction=Decimal("0.1325"))
    probs = GradeProbs(
        by_grade={
            "7.5": Decimal("0.20"),
            "8": Decimal("0.30"),
            "8.5": Decimal("0.25"),
            "9": Decimal("0.15"),
            "10": Decimal("0.05"),
        },
        p_below=Decimal("0.05"),
    )
    values = _values(
        "disagree-card", "5", {"7.5": "60", "8": "80", "8.5": "90", "9": "100", "10": "150"}
    )
    a = analyze_standalone(
        "disagree-card", probs, values, _flat_book("50.00"), "current", config, AS_OF
    )
    assert a.sticker.verdict == "submit"
    assert a.sticker.net_gain == Decimal("26.25")
    assert a.take_home is not None
    assert a.take_home.net_gain == Decimal("16.146875")
    assert a.take_home.verdict == "hold"
    assert a.overall_verdict == "hold"
    assert "views disagree" in a.overall_reason


def test_prob_shift_flip_point_recorded():
    """A near-threshold card: shifting 0.05 mass 10->9 (V10 - V9 = 500) swings
    the gain by -25 and flips the base submit to don't bother; the flip is
    recorded under category 'prob' and the card is labeled fragile.

    Values 60/80/90/100/600, raw 5, probs .20/.30/.25/.15/.05, below .05.
    EV = 12 + 24 + 22.5 + 15 + 30 + 0.25 = 103.75; C = 78
    gain = 103.75 - 78 - 5 = 20.75 -> base submit.
    Shift 10->9: gain 20.75 - 25 = -4.25 -> dont_bother.
    """
    probs = GradeProbs(
        by_grade={
            "7.5": Decimal("0.20"),
            "8": Decimal("0.30"),
            "8.5": Decimal("0.25"),
            "9": Decimal("0.15"),
            "10": Decimal("0.05"),
        },
        p_below=Decimal("0.05"),
    )
    values = _values(
        "threshold-card", "5", {"7.5": "60", "8": "80", "8.5": "90", "9": "100", "10": "600"}
    )
    a = analyze_standalone(
        "threshold-card", probs, values, _flat_book("78.00"), "current", CONFIG, AS_OF
    )
    assert a.sticker.base_verdict == "submit"
    prob_flips = [f for f in a.sticker.sensitivity.flips if f.category == "prob"]
    ten_to_nine = next(f for f in prob_flips if "10->9" in f.description)
    assert ten_to_nine.shocked_gain == Decimal("-4.25")
    assert ten_to_nine.new_verdict == "dont_bother"
    assert a.sticker.sensitivity.robustness == "fragile"


def test_custom_grade_set_flows_through():
    """The grade set is config data: a 3-grade set works end to end."""
    config = EngineConfig(grades=("8", "9", "10"))
    probs = GradeProbs(
        by_grade={"8": Decimal("0.30"), "9": Decimal("0.40"), "10": Decimal("0.25")},
        p_below=Decimal("0.05"),
    )
    by_kind = {
        "raw": _snap("tri", "raw", "50", date(2026, 7, 20)),
        "psa8": _snap("tri", "psa8", "100", date(2026, 7, 20)),
        "psa9": _snap("tri", "psa9", "200", date(2026, 7, 20)),
        "psa10": _snap("tri", "psa10", "800", date(2026, 7, 20)),
    }
    values = CardValues(card_id="tri", grades=config.grades, by_kind=by_kind)
    a = analyze_standalone("tri", probs, values, _flat_book("50.00"), "current", config, AS_OF)
    # EV = 30 + 80 + 200 + .05x50 = 312.50; gain = 312.50 - 50 - 50 = 212.50
    assert a.sticker.net_gain == Decimal("212.50")
    assert a.sticker.verdict == "submit"
