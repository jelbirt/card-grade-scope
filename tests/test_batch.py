"""Batch analysis: amortization invariant, golden 3-card batch, marginal
classification, tier minimums, return-shipping band boundaries."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from gradescope import paths
from gradescope.costs import SharedCosts, return_shipping_fee
from gradescope.engine import EngineConfig, analyze_batch
from gradescope.models import Batch, GradeProbs
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
    """Hand computation (current scenario, N=3, all on regular):

    Declared values: mewtwo 250.50; darkrai .30x75+.40x100+.20x170+.02x500
    +.08x65 = 111.70; catcher .10x60+.30x85+.40x140+.15x320+.05x55 = 138.25.
    Total DV 500.45 -> return band 1-4 items / <=2000 = 19.99.
    Shared S = 25.00 + 19.99 + 8.00 = 52.99; shares (1e-6 floor, remainder to
    first) = [17.663334, 17.663333, 17.663333].
    f_i each = 79.99 + 5.079365 (CT tax) + 0.30 = 85.369365.

    Sticker net gains:
      mewtwo  250.50 - (85.369365 + 17.663334) - 90 = 57.467301
      darkrai 111.70 - (85.369365 + 17.663333) - 65 = -56.332698
      catcher 138.25 - (85.369365 + 17.663333) - 55 = -19.782698
      total = -18.648095
    """
    result = analyze_batch(_trio_batch(), probs, values, book, CONFIG, AS_OF)
    assert result.shared.total == Decimal("52.99")
    assert result.shares_by_card["nd-54-mewtwo-ex-full-art"] == Decimal("17.663334")
    assert result.shares_by_card["de-63-darkrai-ex-full-art"] == Decimal("17.663333")
    by_id = {a.card_id: a for a in result.analyses}
    assert by_id["nd-54-mewtwo-ex-full-art"].sticker.net_gain == Decimal("57.467301")
    assert by_id["de-63-darkrai-ex-full-art"].sticker.net_gain == Decimal("-56.332698")
    assert by_id["de-111-pokemon-catcher-secret"].sticker.net_gain == Decimal("-19.782698")
    assert result.total_net_gain["sticker"] == Decimal("-18.648095")
    # Total cost = 3 x 85.369365 + 52.99 = 309.098095
    assert result.total_cost == Decimal("309.098095")


def test_golden_trio_marginals(book, probs, values):
    """Removing darkrai (N=2: shares 26.495 each):
      mewtwo 250.50 - 111.864365 - 90 = 48.635635
      catcher 138.25 - 111.864365 - 55 = -28.614365
      total without darkrai = 20.021270
      removal delta = 20.021270 - (-18.648095) = +38.669365 -> drag.
    Mewtwo is standalone-positive (solo sticker gain 22.140635 > 0) and its
    removal delta is negative (the batch is worse without it)."""
    result = analyze_batch(_trio_batch(), probs, values, book, CONFIG, AS_OF)
    m = {m.card_id: m for m in result.marginals}
    darkrai = m["de-63-darkrai-ex-full-art"]
    assert darkrai.removal_delta["sticker"] == Decimal("38.669365")
    assert darkrai.category["sticker"] == "drag"
    mewtwo = m["nd-54-mewtwo-ex-full-art"]
    assert mewtwo.standalone_gain["sticker"] == Decimal("22.140635")
    assert mewtwo.removal_delta["sticker"] < 0
    assert mewtwo.category["sticker"] == "standalone"
    catcher = m["de-111-pokemon-catcher-secret"]
    assert catcher.category["sticker"] == "drag"


def test_drag_removal_raises_total(book, probs, values):
    """Property: dropping every sticker-drag card leaves a batch whose total
    sticker net gain is higher than the original."""
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
            p7=Decimal("0.25"),
            p8=Decimal("0.40"),
            p9=Decimal("0.25"),
            p10=Decimal("0.05"),
            p_below7=Decimal("0.05"),
        )
        for cid in ids
    }
    snaps = load_snapshots(SAMPLE / "values.jsonl")
    template = freshest_values(snaps, ["de-46-zoroark-holo"])["de-46-zoroark-holo"]
    values = {cid: CardValues(card_id=cid, by_kind=template.by_kind) for cid in ids}
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
