"""Batch analysis: amortization invariant, golden 3-card batch, marginal
classification, batch-size N±1 shock, tier minimums, return-shipping bands."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from gradescope import paths
from gradescope.costs import SharedCosts, return_shipping_fee
from gradescope.engine import EngineConfig, analyze_batch
from gradescope.models import Batch, GradeProbs, ValueSnapshot
from gradescope.report import render_batch
from gradescope.validate import load_cost_book, load_probabilities, load_snapshots
from gradescope.values import CardValues, freshest_values

SAMPLE = paths.repo_root() / "data" / "sample"
FROZEN_BOOK = Path(__file__).parent / "golden" / "fixtures" / "cost-book-frozen.yaml"
AS_OF = date(2026, 8, 1)
CONFIG = EngineConfig()

TRIO = (
    "nd-54-mewtwo-ex-full-art",
    "de-63-darkrai-ex-full-art",
    "de-111-pokemon-catcher-secret",
)


@pytest.fixture(scope="module")
def book():
    return load_cost_book(FROZEN_BOOK)


@pytest.fixture(scope="module")
def probs():
    return load_probabilities(SAMPLE / "probabilities.yaml")


@pytest.fixture(scope="module")
def values():
    snaps = load_snapshots(SAMPLE / "values.jsonl")
    return freshest_values(snaps, list(TRIO) + ["de-46-zoroark-holo", "nd-1-deerling-common"])


def _trio_batch() -> Batch:
    return Batch(
        name="trio",
        pricing_scenario="current",
        membership_already_held=False,
        card_ids=TRIO,
    )


def test_amortization_invariant_exact():
    """sum(shares) == S exactly, including a non-terminating S/N (52.99/3)."""
    shared = SharedCosts(lines={"a": Decimal("25.00"), "b": Decimal("19.99"), "c": Decimal("8.00")})
    for n in (1, 2, 3, 6, 7, 20, 33):
        shares = shared.shares(n)
        assert sum(shares) == shared.total, n
        assert max(shares) - min(shares) <= Decimal("0.000001")


def test_golden_trio_batch(book, probs, values):
    """Hand computation (current scenario, N=3, all on regular, friction 0):

    Declared values:
      mewtwo  301.50 (see golden EV test)
      darkrai .30x80 + .30x100 + .20x120 + .15x170 + .01x500 + .04x65
              = 24 + 30 + 24 + 25.50 + 5 + 2.60 = 111.10
      catcher .10x65 + .25x85 + .25x105 + .25x140 + .10x320 + .05x55
              = 6.50 + 21.25 + 26.25 + 35 + 32 + 2.75 = 123.75
    Total DV 536.35 -> return band 1-4 items / <=2000 = 19.99.
    Shared S = 25.00 + 19.99 + 8.00 = 52.99; shares (1e-6 floor, remainder to
    first) = [17.663334, 17.663333, 17.663333]. f_i each = 85.369365.

    Net gains (EV(graded) equals DV since alpha = 1):
      mewtwo  301.50 - (85.369365 + 17.663334) - 90 = 108.467301
      darkrai 111.10 - (85.369365 + 17.663333) - 65 = -56.932698
      catcher 123.75 - (85.369365 + 17.663333) - 55 = -34.282698
      total = 17.251905;  total cost = 3 x 85.369365 + 52.99 = 309.098095
    """
    result = analyze_batch(_trio_batch(), probs, values, book, CONFIG, AS_OF)
    assert result.view_names == ("sticker",)
    assert result.shared.total == Decimal("52.99")
    assert result.shares_by_card["nd-54-mewtwo-ex-full-art"] == Decimal("17.663334")
    assert result.shares_by_card["de-63-darkrai-ex-full-art"] == Decimal("17.663333")
    by_id = {a.card_id: a for a in result.analyses}
    assert by_id["nd-54-mewtwo-ex-full-art"].sticker.net_gain == Decimal("108.467301")
    assert by_id["de-63-darkrai-ex-full-art"].sticker.net_gain == Decimal("-56.932698")
    assert by_id["de-111-pokemon-catcher-secret"].sticker.net_gain == Decimal("-34.282698")
    assert result.total_net_gain["sticker"] == Decimal("17.251905")
    assert result.total_cost == Decimal("309.098095")


def test_golden_trio_marginals(book, probs, values):
    """Removing darkrai (N=2: shares 26.495 each):
      mewtwo  301.50 - 111.864365 - 90 = 99.635635
      catcher 123.75 - 111.864365 - 55 = -43.114365
      total without darkrai = 56.521270
      removal delta = 56.521270 - 17.251905 = +39.269365 -> drag.
    Mewtwo is standalone-positive (solo gain 73.140635 > 0) and the batch is
    worse without it (negative removal delta)."""
    result = analyze_batch(_trio_batch(), probs, values, book, CONFIG, AS_OF)
    m = {m.card_id: m for m in result.marginals}
    darkrai = m["de-63-darkrai-ex-full-art"]
    assert darkrai.removal_delta["sticker"] == Decimal("39.269365")
    assert darkrai.category["sticker"] == "drag"
    mewtwo = m["nd-54-mewtwo-ex-full-art"]
    assert mewtwo.standalone_gain["sticker"] == Decimal("73.140635")
    assert mewtwo.removal_delta["sticker"] < 0
    assert mewtwo.category["sticker"] == "standalone"
    catcher = m["de-111-pokemon-catcher-secret"]
    assert catcher.category["sticker"] == "drag"


def test_drag_removal_raises_total(book, probs, values):
    """Property: dropping every drag card leaves a batch whose total net gain
    is higher than the original."""
    result = analyze_batch(_trio_batch(), probs, values, book, CONFIG, AS_OF)
    keep = tuple(m.card_id for m in result.marginals if m.category["sticker"] != "drag")
    assert keep  # mewtwo survives
    smaller = Batch(
        name="pruned", pricing_scenario="current", membership_already_held=False, card_ids=keep
    )
    pruned = analyze_batch(smaller, probs, values, book, CONFIG, AS_OF)
    assert pruned.total_net_gain["sticker"] > result.total_net_gain["sticker"]


def test_tier_minimum_flag_fires_value_restored(book, probs, values):
    """A 3-card batch under value_restored is below value_bulk's 20-card
    minimum -> flag names the tier, the shortfall, and a filler cost."""
    batch = Batch(
        name="vr",
        pricing_scenario="value_restored",
        membership_already_held=False,
        card_ids=TRIO,
    )
    result = analyze_batch(batch, probs, values, book, CONFIG, AS_OF)
    assert len(result.tier_minimum_flags) == 1
    flag = result.tier_minimum_flags[0]
    assert "value_bulk" in flag and "20-card minimum" in flag and "17 filler" in flag


def test_membership_added_when_bulk_tier_used(book):
    """20 sub-$500 cards under value_restored select value_bulk (members only)
    -> shared pool gains membership + CT tax on it."""
    n = 20
    ids = tuple(f"clone-{i:02d}" for i in range(n))
    probs = {
        cid: GradeProbs(
            by_grade={
                "7.5": Decimal("0.25"),
                "8": Decimal("0.40"),
                "8.5": Decimal("0.15"),
                "9": Decimal("0.10"),
                "10": Decimal("0.05"),
            },
            p_below=Decimal("0.05"),
        )
        for cid in ids
    }
    snaps = load_snapshots(SAMPLE / "values.jsonl")
    template = freshest_values(snaps, ["de-46-zoroark-holo"])["de-46-zoroark-holo"]
    values = {
        cid: CardValues(card_id=cid, grades=CONFIG.grades, by_kind=template.by_kind) for cid in ids
    }
    batch = Batch(
        name="bulk20",
        pricing_scenario="value_restored",
        membership_already_held=False,
        card_ids=ids,
    )
    result = analyze_batch(batch, probs, values, book, CONFIG, AS_OF)
    tiers = {a.cost.tier.name for a in result.analyses}
    assert tiers == {"value_bulk"}
    assert "Collectors Club membership (standard)" in result.shared.lines
    assert result.shared.lines["Collectors Club membership (standard)"] == Decimal("149.00")
    assert result.shared.lines["sales tax on membership"] == Decimal("9.461500")
    assert not result.tier_minimum_flags
    # membership_already_held drops both lines
    held = Batch(
        name="bulk20h",
        pricing_scenario="value_restored",
        membership_already_held=True,
        card_ids=ids,
    )
    result_held = analyze_batch(held, probs, values, book, CONFIG, AS_OF)
    assert "Collectors Club membership (standard)" not in result_held.shared.lines


def test_return_shipping_band_boundaries(book):
    """PSA chart boundaries at 4/5, 9/10, 19/20 items (<= $2,000 band)."""
    v = Decimal(500)
    assert return_shipping_fee(book, 4, v) == Decimal("19.99")
    assert return_shipping_fee(book, 5, v) == Decimal("24.99")
    assert return_shipping_fee(book, 9, v) == Decimal("24.99")
    assert return_shipping_fee(book, 10, v) == Decimal("29.99")
    assert return_shipping_fee(book, 19, v) == Decimal("29.99")
    assert return_shipping_fee(book, 20, v) == Decimal("29.99") + Decimal("0.39")
    assert return_shipping_fee(book, 25, v) == Decimal("29.99") + Decimal("0.39") * 6
    # value-band escalation
    assert return_shipping_fee(book, 4, Decimal(5000)) == Decimal("34.99")


# ------------------------------------------------------ batch-size N±1 shock


def _snap(card_id: str, kind: str, value: str) -> ValueSnapshot:
    return ValueSnapshot(
        card_id=card_id,
        kind=kind,
        value=Decimal(value),
        currency="USD",
        source_name="FIXTURE",
        source_url="https://example.com/fixture",
        date_observed=date(2026, 7, 20),
    )


def _certain_ten(card_id: str, v10: str) -> tuple[GradeProbs, CardValues]:
    """A card that grades PSA 10 with certainty: DV == V10, raw fixed at 100."""
    probs = GradeProbs(
        by_grade={g: Decimal(1) if g == "10" else Decimal(0) for g in CONFIG.grades},
        p_below=Decimal(0),
    )
    by_kind = {"raw": _snap(card_id, "raw", "100")}
    for g in CONFIG.grades:
        by_kind[f"psa{g}"] = _snap(card_id, f"psa{g}", v10 if g == "10" else "50")
    return probs, CardValues(card_id=card_id, grades=CONFIG.grades, by_kind=by_kind)


def test_golden_trio_size_shocks_stable(book, probs, values):
    """Trio (N=3, S=52.99): shares 26.495 at N-1, 13.2475 at N+1. Mewtwo's
    submit and the others' don't-bother survive both directions:
      mewtwo  108.467301 - 8.831666 = 99.635635 / + 4.415834 = 112.883135
      darkrai -56.932698 - 8.831667 = -65.764365 / + 4.415833 = -52.516865
    """
    result = analyze_batch(_trio_batch(), probs, values, book, CONFIG, AS_OF)
    m = {m.card_id: m for m in result.marginals}
    mewtwo = m["nd-54-mewtwo-ex-full-art"].size_shocks
    assert [s.n for s in mewtwo] == [2, 4]
    assert mewtwo[0].share == Decimal("26.495")
    assert mewtwo[1].share == Decimal("13.2475")
    assert mewtwo[0].gain["sticker"] == Decimal("99.635635")
    assert mewtwo[1].gain["sticker"] == Decimal("112.883135")
    assert {s.verdict["sticker"] for s in mewtwo} == {"submit"}
    darkrai = m["de-63-darkrai-ex-full-art"].size_shocks
    assert darkrai[0].gain["sticker"] == Decimal("-65.764365")
    assert darkrai[1].gain["sticker"] == Decimal("-52.516865")
    assert {s.verdict["sticker"] for s in darkrai} == {"dont_bother"}
    table = render_batch(result, detail=False)
    assert table.count("stable") == 3


def test_size_shock_flips_engineered_pair(book):
    """Batch of 2 certain-10 cards, regular tier (f_i 85.369365), S = 52.99,
    shares 26.495 each -> per-card cost 111.864365, raw 100.

    A (V10 245): gain 33.135635 -> submit.
      N-1 (share 52.99):  6.640635 -> hold (flip);  N+1 (share 17.663334):
      41.967301 -> submit (stable).
    B (V10 231): gain 19.135635 -> hold.
      N-1: -7.359365 -> don't bother; N+1: 27.967301 -> submit (both flip).
    """
    probs_a, values_a = _certain_ten("flip-a", "245")
    probs_b, values_b = _certain_ten("flip-b", "231")
    batch = Batch(
        name="pair",
        pricing_scenario="current",
        membership_already_held=False,
        card_ids=("flip-a", "flip-b"),
    )
    result = analyze_batch(
        batch,
        {"flip-a": probs_a, "flip-b": probs_b},
        {"flip-a": values_a, "flip-b": values_b},
        book,
        CONFIG,
        AS_OF,
    )
    m = {m.card_id: m for m in result.marginals}
    a_minus, a_plus = m["flip-a"].size_shocks
    assert (a_minus.n, a_minus.share) == (1, Decimal("52.99"))
    assert a_minus.gain["sticker"] == Decimal("6.640635")
    assert a_minus.verdict["sticker"] == "hold"
    assert (a_plus.n, a_plus.share) == (3, Decimal("17.663334"))
    assert a_plus.gain["sticker"] == Decimal("41.967301")
    assert a_plus.verdict["sticker"] == "submit"
    b_minus, b_plus = m["flip-b"].size_shocks
    assert b_minus.gain["sticker"] == Decimal("-7.359365")
    assert b_minus.verdict["sticker"] == "dont_bother"
    assert b_plus.gain["sticker"] == Decimal("27.967301")
    assert b_plus.verdict["sticker"] == "submit"
    table = render_batch(result, detail=False)
    assert "flips N-1" in table  # A: only the smaller batch flips it
    assert "flips both" in table  # B: flips in both directions


def test_size_shock_single_card_batch_has_no_minus(book):
    """N=1: N-1 is undefined -> only the N+1 probe, and the report says so."""
    probs_a, values_a = _certain_ten("solo", "245")
    batch = Batch(
        name="solo",
        pricing_scenario="current",
        membership_already_held=False,
        card_ids=("solo",),
    )
    result = analyze_batch(batch, {"solo": probs_a}, {"solo": values_a}, book, CONFIG, AS_OF)
    (shock,) = result.marginals[0].size_shocks
    assert shock.n == 2
    assert shock.share == Decimal("26.495")
    assert shock.gain["sticker"] == Decimal("33.135635")
    assert shock.verdict["sticker"] == "submit"  # hold at N=1 -> submit at N+1
    table = render_batch(result, detail=False)
    assert "N-1 n/a (batch of 1)" in table
    assert "flips N+1" in table
