"""Sensitivity grid, flip points, and the final verdict rules (SPEC §6)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from gradescope import paths
from gradescope.engine import EngineConfig, analyze_standalone
from gradescope.models import (
    CostBook,
    CostLine,
    GradeProbs,
    ServiceLevel,
    Source,
    Supplies,
    ValueSnapshot,
)
from gradescope.validate import load_cost_book, load_probabilities, load_snapshots
from gradescope.values import CardValues, freshest_values

SAMPLE = paths.repo_root() / "data" / "sample"
FROZEN_BOOK = Path(__file__).parent / "golden" / "fixtures" / "cost-book-frozen.yaml"
AS_OF = date(2026, 8, 1)
CONFIG = EngineConfig()

SRC = Source(url="https://example.com/fixture", date_accessed=date(2026, 8, 1))


def _snap(card_id: str, kind: str, value: str, observed: date = date(2026, 7, 20)) -> ValueSnapshot:
    return ValueSnapshot(
        card_id=card_id,
        kind=kind,
        value=Decimal(value),
        currency="USD",
        source_name="FIXTURE",
        source_url="https://example.com/fixture",
        date_observed=observed,
    )


def _values(
    card_id: str, raw: str, v7: str, v8: str, v9: str, v10: str, observed=date(2026, 7, 20)
):
    return CardValues(
        card_id=card_id,
        by_kind={
            "raw": _snap(card_id, "raw", raw, observed),
            "psa7": _snap(card_id, "psa7", v7, observed),
            "psa8": _snap(card_id, "psa8", v8, observed),
            "psa9": _snap(card_id, "psa9", v9, observed),
            "psa10": _snap(card_id, "psa10", v10, observed),
        },
    )


def _cheap_book() -> CostBook:
    """Tiny inline book: one tier, no tax, no membership, zero shared costs."""
    from gradescope.models import ReturnShippingBand

    return CostBook(
        date_accessed=date(2026, 8, 1),
        currency="USD",
        service_levels=(
            ServiceLevel(
                name="flat",
                status="active",
                fee_per_card=Decimal("5.00"),
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


@pytest.fixture(scope="module")
def frozen_book():
    return load_cost_book(FROZEN_BOOK)


def test_solo_mewtwo_fragile_submit_downgraded_to_hold(frozen_book):
    """Solo Mewtwo sticker: base rule says submit (gain 22.140635) but a -10%
    graded-value shock swings EV by 24.60 -> gain -2.459365 <= 0, so the final
    verdict is HOLD (not robust). This is the deliberate Task 5 update of the
    Task 2 provisional expectation."""
    probs = load_probabilities(SAMPLE / "probabilities.yaml")["nd-54-mewtwo-ex-full-art"]
    snaps = load_snapshots(SAMPLE / "values.jsonl")
    values = freshest_values(snaps, ["nd-54-mewtwo-ex-full-art"])["nd-54-mewtwo-ex-full-art"]
    a = analyze_standalone(
        "nd-54-mewtwo-ex-full-art", probs, values, frozen_book, "current", CONFIG, AS_OF
    )
    assert a.sticker.base_verdict == "submit"
    assert a.sticker.verdict == "hold"
    assert "not robust" in a.sticker.reason
    assert a.sticker.sensitivity.robustness == "fragile"
    assert a.sticker.sensitivity.min_gain_under_value_shocks == Decimal("-39.359365")
    flip_categories = {f.category for f in a.sticker.sensitivity.flips}
    assert "value" in flip_categories
    assert a.overall_verdict == "hold"


def test_robust_submit_survives(frozen_book):
    """A high-margin card survives every shock: base submit stands.

    raw 100; graded 400/600/900/2000 with p .10/.30/.40/.15, below7 .05.
    EV(graded) = 40+180+360+300+5 = 885; C = 138.359365 (solo regular, DV<=1500
    ... DV = 40+180+360+300+.05x100=885 -> regular). gain = 885-138.36-100 =
    646.64; -25% graded shock = -220 swing -> still ~426 > 0."""
    probs = GradeProbs(
        p7=Decimal("0.10"),
        p8=Decimal("0.30"),
        p9=Decimal("0.40"),
        p10=Decimal("0.15"),
        p_below7=Decimal("0.05"),
    )
    values = _values("robust-card", "100", "400", "600", "900", "2000")
    a = analyze_standalone("robust-card", probs, values, frozen_book, "current", CONFIG, AS_OF)
    assert a.sticker.base_verdict == "submit"
    assert a.sticker.verdict == "submit"
    assert a.sticker.sensitivity.robustness == "robust"
    assert not a.sticker.sensitivity.flips
    assert a.take_home.verdict == "submit"
    assert a.overall_verdict == "submit"
    assert a.upcharge_risk  # psa10 2000 > regular max 1500 -> warned


def test_stale_snapshots_downgrade_submit_to_hold(frozen_book):
    """Same robust card, but snapshots observed 200 days before as-of:
    submit -> hold with the stale reason naming the threshold."""
    probs = GradeProbs(
        p7=Decimal("0.10"),
        p8=Decimal("0.30"),
        p9=Decimal("0.40"),
        p10=Decimal("0.15"),
        p_below7=Decimal("0.05"),
    )
    values = _values("stale-card", "100", "400", "600", "900", "2000", observed=date(2026, 1, 13))
    a = analyze_standalone("stale-card", probs, values, frozen_book, "current", CONFIG, AS_OF)
    assert a.stale_kinds == ["raw", "psa7", "psa8", "psa9", "psa10"]
    assert a.sticker.base_verdict == "submit"
    assert a.sticker.verdict == "hold"
    assert "stale snapshots" in a.sticker.reason
    assert a.overall_verdict == "hold"


def test_views_disagree_yields_overall_hold():
    """Constructed so sticker is a robust submit while take-home is a thin hold:
    raw 5, EV(all outcomes) = 77, C = 5 (cheap flat book).
    sticker gain = 77 - 5 - 5 = 67 >= 20, robust (25% swing ~19.2 < 67).
    take-home gain = 0.87x77 - 5 - 4.35 = 57.64 ... still submit. Push C:
    use C = 50 via fee: sticker 22, take-home 12.64 -> disagree -> HOLD."""
    from dataclasses import replace as dc_replace

    probs = GradeProbs(
        p7=Decimal("0.20"),
        p8=Decimal("0.40"),
        p9=Decimal("0.30"),
        p10=Decimal("0.05"),
        p_below7=Decimal("0.05"),
    )
    values = _values("disagree-card", "5", "60", "80", "100", "150")
    book = _cheap_book()
    fee50 = dc_replace(book.service_levels[0], fee_per_card=Decimal("50.00"))
    book = dc_replace(book, service_levels=(fee50,))
    a = analyze_standalone("disagree-card", probs, values, book, "current", CONFIG, AS_OF)
    # sticker: EV = .2x60+.4x80+.3x100+.05x150+.05x5 = 12+32+30+7.5+0.25 = 81.75
    #          gain = 81.75 - 50 - 5 = 26.75 -> submit; -25% graded swing 20.375
    #          -> min gain 6.375 > 0 -> robust enough to keep submit
    assert a.sticker.verdict == "submit"
    assert a.sticker.net_gain == Decimal("26.75")
    # take-home: gain = 0.87x(81.75-5) - 50 = 66.7725 - 50 - ... compute below
    assert a.take_home.verdict == "hold"
    assert a.overall_verdict == "hold"
    assert "views disagree" in a.overall_reason


def test_prob_shift_flip_point_recorded(frozen_book):
    """Mewtwo solo: shifting 0.05 mass 10->9 removes half the top mass and
    flips the base submit; the flip is recorded under category 'prob'."""
    probs = load_probabilities(SAMPLE / "probabilities.yaml")["nd-54-mewtwo-ex-full-art"]
    snaps = load_snapshots(SAMPLE / "values.jsonl")
    values = freshest_values(snaps, ["nd-54-mewtwo-ex-full-art"])["nd-54-mewtwo-ex-full-art"]
    a = analyze_standalone(
        "nd-54-mewtwo-ex-full-art", probs, values, frozen_book, "current", CONFIG, AS_OF
    )
    prob_flips = [f for f in a.sticker.sensitivity.flips if f.category == "prob"]
    assert any("10->9" in f.description for f in prob_flips)
    # 0.05 x (750-260) = 24.50 swing -> 22.140635 - 24.50 = -2.359365
    ten_to_nine = next(f for f in prob_flips if "10->9" in f.description)
    assert ten_to_nine.shocked_gain == Decimal("-2.359365")
    assert ten_to_nine.new_verdict == "dont_bother"
