"""Break-even solver: hand-computed threshold, edge kinds, monotonicity."""

from decimal import Decimal

from gradescope.engine import solve_breakeven
from gradescope.models import GradeProbs

# Mewtwo sticker-view inputs (see tests/golden/test_golden_ev.py):
MEWTWO_PROBS = GradeProbs(
    p7=Decimal("0.10"),
    p8=Decimal("0.35"),
    p9=Decimal("0.40"),
    p10=Decimal("0.10"),
    p_below7=Decimal("0.05"),
)
MEWTWO_NET = {7: Decimal(110), 8: Decimal(160), 9: Decimal(260), 10: Decimal(750)}
MEWTWO_BELOW7 = Decimal(90)  # alpha=1 x raw 90
MEWTWO_RAW = Decimal(90)
MEWTWO_COST = Decimal("138.359365")


def test_threshold_hand_computed():
    """Hand computation:
    A (non-top conditional EV) = (.10x110 + .35x160 + .40x260 + .05x90) / 0.90
                               = 175.50 / 0.90 = 195
    t* = (C + V_raw - A) / (V10 - A) = (138.359365 + 90 - 195) / (750 - 195)
       = 33.359365 / 555 = 0.06010696396396...
    """
    be = solve_breakeven(MEWTWO_PROBS, MEWTWO_NET, MEWTWO_BELOW7, MEWTWO_RAW, MEWTWO_COST)
    assert be.kind == "threshold"
    assert be.p10_min.quantize(Decimal("1e-9")) == Decimal("0.060106964")


def test_never_breaks_even():
    """Deerling shape: PSA 10 at 35 can't cover cost 138.36 + raw 0.25."""
    probs = GradeProbs(
        p7=Decimal("0.15"),
        p8=Decimal("0.40"),
        p9=Decimal("0.35"),
        p10=Decimal("0.05"),
        p_below7=Decimal("0.05"),
    )
    net = {7: Decimal(5), 8: Decimal(8), 9: Decimal(15), 10: Decimal(35)}
    be = solve_breakeven(probs, net, Decimal("0.25"), Decimal("0.25"), Decimal("138.359365"))
    assert be.kind == "never"
    assert be.p10_min is None


def test_always_positive():
    """Non-top mix alone clears cost + raw:
    A = (.15x200 + .40x200 + .35x200 + .05x10) / 0.95 = 180.50 / 0.95 = 190
    C + V_raw = 138.359365 + 10 = 148.359365 < 190 -> always.
    """
    probs = GradeProbs(
        p7=Decimal("0.15"),
        p8=Decimal("0.40"),
        p9=Decimal("0.35"),
        p10=Decimal("0.05"),
        p_below7=Decimal("0.05"),
    )
    net = {7: Decimal(200), 8: Decimal(200), 9: Decimal(200), 10: Decimal(300)}
    be = solve_breakeven(probs, net, Decimal(10), Decimal(10), Decimal("138.359365"))
    assert be.kind == "always"
    assert be.p10_min == Decimal(0)


def test_all_top_mass_edge():
    """p10 = 1 leaves no non-top mix; only the all-top endpoint is defined."""
    probs = GradeProbs(
        p7=Decimal(0), p8=Decimal(0), p9=Decimal(0), p10=Decimal(1), p_below7=Decimal(0)
    )
    be_ok = solve_breakeven(probs, MEWTWO_NET, MEWTWO_BELOW7, MEWTWO_RAW, MEWTWO_COST)
    assert be_ok.kind == "always"  # 750 - 138.36 - 90 > 0
    be_no = solve_breakeven(probs, MEWTWO_NET, MEWTWO_BELOW7, MEWTWO_RAW, Decimal(700))
    assert be_no.kind == "never"  # 750 - 700 - 90 < 0


def test_threshold_monotonic_in_cost():
    """Property (tasks/plan.md Task 3): higher C_i -> higher p10*."""
    previous = None
    for cost in (Decimal(120), Decimal(160), Decimal(200), Decimal(300), Decimal(400)):
        be = solve_breakeven(MEWTWO_PROBS, MEWTWO_NET, MEWTWO_BELOW7, MEWTWO_RAW, cost)
        assert be.kind == "threshold"
        if previous is not None:
            assert be.p10_min > previous
        previous = be.p10_min


def test_inverse_kind_detected():
    """PSA 10 valued below the non-top mix EV — pathological snapshots."""
    probs = MEWTWO_PROBS
    net = {7: Decimal(300), 8: Decimal(300), 9: Decimal(300), 10: Decimal(100)}
    # A = (.10+.35+.40)x300/0.9 + tiny below7 term -> well above V10=100.
    be = solve_breakeven(probs, net, Decimal(200), Decimal(50), Decimal(240))
    assert be.kind == "inverse"
