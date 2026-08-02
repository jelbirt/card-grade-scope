"""Break-even solver: hand-computed threshold, edge kinds, monotonicity."""

from decimal import Decimal

from gradescope.engine import solve_breakeven
from gradescope.models import DEFAULT_GRADES, GradeProbs

# Mewtwo sticker-view inputs (see tests/golden/test_golden_ev.py):
MEWTWO_PROBS = GradeProbs(
    by_grade={
        "7.5": Decimal("0.10"),
        "8": Decimal("0.25"),
        "8.5": Decimal("0.15"),
        "9": Decimal("0.25"),
        "10": Decimal("0.20"),
    },
    p_below=Decimal("0.05"),
)
MEWTWO_NET = {
    "7.5": Decimal(120),
    "8": Decimal(160),
    "8.5": Decimal(200),
    "9": Decimal(260),
    "10": Decimal(750),
}
MEWTWO_BELOW = Decimal(90)  # alpha=1 x raw 90
MEWTWO_RAW = Decimal(90)
MEWTWO_COST = Decimal("138.359365")


def _solve(probs, net, below, raw, cost):
    return solve_breakeven(probs, DEFAULT_GRADES, net, below, raw, cost)


def test_threshold_hand_computed():
    """Hand computation:
    A = (.10x120 + .25x160 + .15x200 + .25x260 + .05x90) / 0.80
      = 151.50 / 0.80 = 189.375
    t* = (138.359365 + 90 - 189.375) / (750 - 189.375) = 38.984365 / 560.625
       = 0.0695373...
    """
    be = _solve(MEWTWO_PROBS, MEWTWO_NET, MEWTWO_BELOW, MEWTWO_RAW, MEWTWO_COST)
    assert be.kind == "threshold"
    assert be.p_top_min.quantize(Decimal("1e-6")) == Decimal("0.069537")


def test_never_breaks_even():
    """Deerling shape: PSA 10 at 35 can't cover cost 138.36 + raw 0.25."""
    probs = GradeProbs(
        by_grade={
            "7.5": Decimal("0.10"),
            "8": Decimal("0.30"),
            "8.5": Decimal("0.25"),
            "9": Decimal("0.25"),
            "10": Decimal("0.05"),
        },
        p_below=Decimal("0.05"),
    )
    net = {
        "7.5": Decimal(4),
        "8": Decimal(8),
        "8.5": Decimal(11),
        "9": Decimal(15),
        "10": Decimal(35),
    }
    be = _solve(probs, net, Decimal("0.25"), Decimal("0.25"), Decimal("138.359365"))
    assert be.kind == "never"
    assert be.p_top_min is None


def test_always_positive():
    """Non-top mix alone clears cost + raw:
    A = (.10x200 + .25x200 + .15x200 + .25x200 + .05x10) / 0.80
      = 150.50 / 0.80 = 188.125 > C + raw = 148.359365 -> always.
    """
    probs = MEWTWO_PROBS
    net = {
        "7.5": Decimal(200),
        "8": Decimal(200),
        "8.5": Decimal(200),
        "9": Decimal(200),
        "10": Decimal(300),
    }
    be = _solve(probs, net, Decimal(10), Decimal(10), Decimal("138.359365"))
    assert be.kind == "always"
    assert be.p_top_min == Decimal(0)


def test_all_top_mass_edge():
    """p10 = 1 leaves no non-top mix; only the all-top endpoint is defined."""
    probs = GradeProbs(
        by_grade={
            "7.5": Decimal(0),
            "8": Decimal(0),
            "8.5": Decimal(0),
            "9": Decimal(0),
            "10": Decimal(1),
        },
        p_below=Decimal(0),
    )
    be_ok = _solve(probs, MEWTWO_NET, MEWTWO_BELOW, MEWTWO_RAW, MEWTWO_COST)
    assert be_ok.kind == "always"  # 750 - 138.36 - 90 > 0
    be_no = _solve(probs, MEWTWO_NET, MEWTWO_BELOW, MEWTWO_RAW, Decimal(700))
    assert be_no.kind == "never"  # 750 - 700 - 90 < 0


def test_threshold_monotonic_in_cost():
    """Property (tasks/plan.md Task 3): higher C_i -> higher p_top*."""
    previous = None
    for cost in (Decimal(120), Decimal(160), Decimal(200), Decimal(300), Decimal(400)):
        be = _solve(MEWTWO_PROBS, MEWTWO_NET, MEWTWO_BELOW, MEWTWO_RAW, cost)
        assert be.kind == "threshold"
        if previous is not None:
            assert be.p_top_min > previous
        previous = be.p_top_min


def test_inverse_kind_detected():
    """PSA 10 valued below the non-top mix EV — pathological snapshots.
    A = (0.75x300 + .05x200) / 0.80 = 235 / 0.80 = 293.75
    g(0) = 293.75 - 240 - 50 = 3.75 >= 0; g(1) = 100 - 290 < 0 -> inverse.
    """
    net = {
        "7.5": Decimal(300),
        "8": Decimal(300),
        "8.5": Decimal(300),
        "9": Decimal(300),
        "10": Decimal(100),
    }
    be = _solve(MEWTWO_PROBS, net, Decimal(200), Decimal(50), Decimal(240))
    assert be.kind == "inverse"
