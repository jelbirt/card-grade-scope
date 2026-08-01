"""The deterministic decision engine (SPEC §6). Stdlib math only.

Verdicts here are PROVISIONAL until the sensitivity task lands (tasks/plan.md
Task 5): the robustness input to submit/hold and the staleness downgrade are
wired there. Reasons are explicit strings so every verdict is explainable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from gradescope.costs import CardCost, card_cost, select_tier, shared_costs
from gradescope.models import GRADES, Batch, CostBook, GradeProbs
from gradescope.values import CardValues

ZERO = Decimal(0)
ONE = Decimal(1)


@dataclass(frozen=True)
class EngineConfig:
    """Knobs with SPEC §12 defaults. config.yaml override lands in Task 6."""

    sale_friction: Decimal = Decimal("0.13")
    alpha: Decimal = Decimal("1.0")  # V_below7 = alpha * V_raw
    min_gain: Decimal = Decimal(20)
    below7_short_circuit: Decimal = Decimal("0.5")
    staleness_days: int = 90


@dataclass(frozen=True)
class BreakEven:
    """Minimum p10 for Net_gain >= 0, holding the relative proportions of the
    non-top outcomes {7, 8, 9, below7} fixed and redistributing (SPEC §6).

    With non-top conditional EV A = (sum of non-top p_g * V_g) / (1 - p10),
    Net_gain(t) = (1-t)*A + t*V10 - C - V_raw is linear in the top mass t:
      kind "threshold": t* = (C + V_raw - A) / (V10 - A), in (0, 1]
      kind "always":    Net_gain >= 0 even at t = 0
      kind "never":     Net_gain < 0 even at t = 1
      kind "inverse":   gain falls as p10 rises (V10 below the non-top mix EV);
                        pathological data — reported, never used as a threshold
    """

    kind: str  # threshold | always | never | inverse
    p10_min: Decimal | None = None


@dataclass(frozen=True)
class ViewResult:
    """One internally-consistent view: sticker (friction 0) or take-home."""

    name: str  # "sticker" | "take_home"
    friction: Decimal
    net_by_grade: dict[int, Decimal]
    net_below7: Decimal
    net_raw: Decimal
    ev_graded: Decimal  # sum p_g * V_g + p_below7 * V_below7
    ev_submit: Decimal
    net_gain: Decimal
    verdict: str  # submit | hold | dont_bother
    reason: str
    breakeven: BreakEven


@dataclass(frozen=True)
class CardAnalysis:
    card_id: str
    probs: GradeProbs
    values: CardValues
    declared_value: Decimal
    cost: CardCost
    short_circuited: bool
    upcharge_risk: bool
    sticker: ViewResult
    take_home: ViewResult
    overall_verdict: str
    overall_reason: str
    stale_kinds: list[str]


def declared_value(probs: GradeProbs, values: CardValues, alpha: Decimal) -> Decimal:
    """Probability-weighted post-grading gross value — what you'd honestly declare."""
    graded = sum((probs.p(g) * values.gross(f"psa{g}") for g in GRADES), ZERO)
    return graded + probs.p_below7 * alpha * values.gross("raw")


def solve_breakeven(
    probs: GradeProbs,
    net_by_grade: dict[int, Decimal],
    net_below7: Decimal,
    net_raw: Decimal,
    cost_total: Decimal,
) -> BreakEven:
    """Closed-form minimum p10 (see BreakEven docstring for the derivation)."""
    v10 = net_by_grade[10]
    non_top_mass = ONE - probs.p10
    gain_at_full_top = v10 - cost_total - net_raw
    if non_top_mass == ZERO:
        # No non-top mix to hold fixed; only the all-top endpoint is defined.
        return (
            BreakEven(kind="always", p10_min=ZERO)
            if gain_at_full_top >= ZERO
            else BreakEven(kind="never")
        )
    non_top_ev = (
        probs.p7 * net_by_grade[7]
        + probs.p8 * net_by_grade[8]
        + probs.p9 * net_by_grade[9]
        + probs.p_below7 * net_below7
    ) / non_top_mass
    gain_at_zero_top = non_top_ev - cost_total - net_raw
    # Gain is linear in top mass t; classify by the endpoint signs.
    if gain_at_zero_top >= ZERO and gain_at_full_top >= ZERO:
        return BreakEven(kind="always", p10_min=ZERO)
    if gain_at_zero_top < ZERO and gain_at_full_top < ZERO:
        return BreakEven(kind="never")
    if gain_at_zero_top >= ZERO:  # positive at t=0, negative at t=1: descending
        return BreakEven(kind="inverse")
    t_star = (cost_total + net_raw - non_top_ev) / (v10 - non_top_ev)
    return BreakEven(kind="threshold", p10_min=t_star)


def _view(
    name: str,
    friction: Decimal,
    probs: GradeProbs,
    values: CardValues,
    cost_total: Decimal,
    config: EngineConfig,
    short_circuited: bool,
) -> ViewResult:
    keep = ONE - friction
    net_by_grade = {g: values.gross(f"psa{g}") * keep for g in GRADES}
    net_raw = values.gross("raw") * keep
    net_below7 = config.alpha * net_raw
    ev_graded = sum((probs.p(g) * net_by_grade[g] for g in GRADES), ZERO)
    ev_graded += probs.p_below7 * net_below7
    ev_submit = ev_graded - cost_total
    net_gain = ev_submit - net_raw
    breakeven = solve_breakeven(probs, net_by_grade, net_below7, net_raw, cost_total)

    if short_circuited:
        verdict, reason = (
            "dont_bother",
            f"expected grade below 7 (p_below7={probs.p_below7} >= {config.below7_short_circuit})",
        )
    elif net_by_grade[10] < cost_total:
        verdict, reason = (
            "dont_bother",
            (
                f"cost floor: even a PSA 10 ({_fmt(net_by_grade[10])}) is below the "
                f"cost {_fmt(cost_total)}"
            ),
        )
    elif net_gain <= ZERO:
        verdict, reason = ("dont_bother", f"net gain {_fmt(net_gain)} is not positive")
    elif net_gain < config.min_gain:
        verdict, reason = (
            "hold",
            f"net gain {_fmt(net_gain)} is positive but under the ${config.min_gain} threshold",
        )
    else:
        verdict, reason = ("submit", f"net gain {_fmt(net_gain)} clears ${config.min_gain}")
    return ViewResult(
        name=name,
        friction=friction,
        net_by_grade=net_by_grade,
        net_below7=net_below7,
        net_raw=net_raw,
        ev_graded=ev_graded,
        ev_submit=ev_submit,
        net_gain=net_gain,
        verdict=verdict,
        reason=reason,
        breakeven=breakeven,
    )


def _fmt(amount: Decimal) -> str:
    return f"${amount.quantize(Decimal('0.01'))}"


def analyze_card(
    card_id: str,
    probs: GradeProbs,
    values: CardValues,
    book: CostBook,
    scenario: str,
    n_cards: int,
    shared_share: Decimal,
    config: EngineConfig,
    as_of: date,
) -> CardAnalysis:
    """Analyze one card given its share of a batch's shared costs.

    For a standalone card, call with n_cards=1 and the full solo shared pool.
    """
    dv = declared_value(probs, values, config.alpha)
    tier = select_tier(book, scenario, dv, n_cards)
    cost = card_cost(book, tier, shared_share)
    short = probs.p_below7 >= config.below7_short_circuit
    upcharge_risk = values.gross("psa10") > tier.max_declared_value

    sticker = _view("sticker", ZERO, probs, values, cost.total, config, short)
    take_home = _view("take_home", config.sale_friction, probs, values, cost.total, config, short)

    if sticker.verdict == take_home.verdict:
        overall, why = sticker.verdict, sticker.reason
    else:
        overall = "hold"
        why = (
            f"views disagree (sticker: {sticker.verdict}, take-home: {take_home.verdict}) — "
            "the decision flips on marketplace fees, so it is assumption-dependent"
        )
    stale = values.stale_kinds(as_of, config.staleness_days)
    return CardAnalysis(
        card_id=card_id,
        probs=probs,
        values=values,
        declared_value=dv,
        cost=cost,
        short_circuited=short,
        upcharge_risk=upcharge_risk,
        sticker=sticker,
        take_home=take_home,
        overall_verdict=overall,
        overall_reason=why,
        stale_kinds=stale,
    )


def analyze_standalone(
    card_id: str,
    probs: GradeProbs,
    values: CardValues,
    book: CostBook,
    scenario: str,
    config: EngineConfig,
    as_of: date,
    membership_already_held: bool = False,
) -> CardAnalysis:
    """Single-card analysis: a batch of one, carrying the whole shared pool."""
    dv = declared_value(probs, values, config.alpha)
    tier = select_tier(book, scenario, dv, 1)
    shared = shared_costs(
        book,
        scenario,
        n_cards=1,
        total_declared=dv,
        tiers_used=[tier],
        membership_already_held=membership_already_held,
    )
    return analyze_card(card_id, probs, values, book, scenario, 1, shared.share(1), config, as_of)


@dataclass(frozen=True)
class MarginalCard:
    """How one card interacts with the batch's shared costs, per view.

    category (per view):
      standalone — net-positive even carrying the whole shared pool alone
      ride_along — positive only because shared costs are split
      drag       — removing it raises total net gain
      negative   — negative in-batch, but removal doesn't help (rare: the
                   shared-cost reshuffle outweighs the card's own loss)
    """

    card_id: str
    standalone_gain: dict[str, Decimal]
    in_batch_gain: dict[str, Decimal]
    removal_delta: dict[str, Decimal]  # total_net_gain(without card) - (with card)
    category: dict[str, str]


@dataclass(frozen=True)
class BatchAnalysis:
    batch: Batch
    analyses: list[CardAnalysis]
    shared: object  # SharedCosts (kept untyped to avoid a circular annotation)
    shares_by_card: dict[str, Decimal]
    total_cost: Decimal
    total_ev_submit: dict[str, Decimal]  # per view
    total_net_gain: dict[str, Decimal]  # per view
    marginals: list[MarginalCard]
    tier_minimum_flags: list[str]


VIEWS = ("sticker", "take_home")


def _view_of(analysis: CardAnalysis, view: str) -> ViewResult:
    return analysis.sticker if view == "sticker" else analysis.take_home


def _batch_card_analyses(
    card_ids: tuple[str, ...],
    scenario: str,
    membership_already_held: bool,
    probs_by_card: dict[str, GradeProbs],
    values_by_card: dict[str, CardValues],
    book: CostBook,
    config: EngineConfig,
    as_of: date,
) -> tuple[list[CardAnalysis], object, dict[str, Decimal]]:
    """Per-card analyses for one card set with a single shared pool (flat split)."""
    n = len(card_ids)
    tiers = {}
    total_dv = ZERO
    for cid in card_ids:
        dv = declared_value(probs_by_card[cid], values_by_card[cid], config.alpha)
        tiers[cid] = select_tier(book, scenario, dv, n)
        total_dv += dv
    shared = shared_costs(
        book,
        scenario,
        n_cards=n,
        total_declared=total_dv,
        tiers_used=list(tiers.values()),
        membership_already_held=membership_already_held,
    )
    shares = shared.shares(n)
    shares_by_card = dict(zip(card_ids, shares, strict=True))
    analyses = [
        analyze_card(
            cid,
            probs_by_card[cid],
            values_by_card[cid],
            book,
            scenario,
            n,
            shares_by_card[cid],
            config,
            as_of,
        )
        for cid in card_ids
    ]
    return analyses, shared, shares_by_card


def _totals(analyses: list[CardAnalysis]) -> tuple[Decimal, dict[str, Decimal], dict[str, Decimal]]:
    total_cost = sum((a.cost.total for a in analyses), ZERO)
    ev = {v: sum((_view_of(a, v).ev_submit for a in analyses), ZERO) for v in VIEWS}
    gain = {v: sum((_view_of(a, v).net_gain for a in analyses), ZERO) for v in VIEWS}
    return total_cost, ev, gain


def _tier_minimum_flags(
    book: CostBook, scenario: str, n: int, total_dv: Decimal, config: EngineConfig
) -> list[str]:
    from gradescope.costs import return_shipping_fee, tax_rate_on

    flags = []
    for lvl in book.orderable_levels(scenario):
        if lvl.min_cards and n < lvl.min_cards:
            filler = lvl.min_cards - n
            per_filler = (
                lvl.fee_per_card
                + lvl.fee_per_card * tax_rate_on(book, "grading_fees")
                + book.supplies.per_card
            )
            shipping_delta = return_shipping_fee(
                book, lvl.min_cards, total_dv
            ) - return_shipping_fee(book, n, total_dv)
            extra = (per_filler * filler + shipping_delta).quantize(Decimal("0.01"))
            membership_note = (
                " (plus Collectors Club membership if not held)" if lvl.membership_required else ""
            )
            flags.append(
                f"batch of {n} is below the {lvl.min_cards}-card minimum for tier "
                f"'{lvl.name}' (${lvl.fee_per_card}/card): adding {filler} filler cards "
                f"would cost about ${extra} in fees/supplies/shipping{membership_note}"
            )
    return flags


def analyze_batch(
    batch: Batch,
    probs_by_card: dict[str, GradeProbs],
    values_by_card: dict[str, CardValues],
    book: CostBook,
    config: EngineConfig,
    as_of: date,
) -> BatchAnalysis:
    """Batch-aware analysis (SPEC §6): flat-split shared pool, per-card marginal
    classification via recompute-with-removal, and tier-minimum flags."""
    analyses, shared, shares_by_card = _batch_card_analyses(
        batch.card_ids,
        batch.pricing_scenario,
        batch.membership_already_held,
        probs_by_card,
        values_by_card,
        book,
        config,
        as_of,
    )
    total_cost, total_ev, total_gain = _totals(analyses)

    marginals: list[MarginalCard] = []
    for cid in batch.card_ids:
        standalone = analyze_standalone(
            cid,
            probs_by_card[cid],
            values_by_card[cid],
            book,
            batch.pricing_scenario,
            config,
            as_of,
            membership_already_held=batch.membership_already_held,
        )
        in_batch = next(a for a in analyses if a.card_id == cid)
        remaining = tuple(c for c in batch.card_ids if c != cid)
        if remaining:
            without, _, _ = _batch_card_analyses(
                remaining,
                batch.pricing_scenario,
                batch.membership_already_held,
                probs_by_card,
                values_by_card,
                book,
                config,
                as_of,
            )
            _, _, gain_without = _totals(without)
        else:
            gain_without = {v: ZERO for v in VIEWS}
        standalone_gain = {v: _view_of(standalone, v).net_gain for v in VIEWS}
        in_batch_gain = {v: _view_of(in_batch, v).net_gain for v in VIEWS}
        removal_delta = {v: gain_without[v] - total_gain[v] for v in VIEWS}
        category = {}
        for v in VIEWS:
            if removal_delta[v] > ZERO:
                category[v] = "drag"
            elif standalone_gain[v] > ZERO:
                category[v] = "standalone"
            elif in_batch_gain[v] > ZERO:
                category[v] = "ride_along"
            else:
                category[v] = "negative"
        marginals.append(
            MarginalCard(
                card_id=cid,
                standalone_gain=standalone_gain,
                in_batch_gain=in_batch_gain,
                removal_delta=removal_delta,
                category=category,
            )
        )

    total_dv = sum(
        (declared_value(probs_by_card[c], values_by_card[c], config.alpha) for c in batch.card_ids),
        ZERO,
    )
    flags = _tier_minimum_flags(book, batch.pricing_scenario, len(batch.card_ids), total_dv, config)
    return BatchAnalysis(
        batch=batch,
        analyses=analyses,
        shared=shared,
        shares_by_card=shares_by_card,
        total_cost=total_cost,
        total_ev_submit=total_ev,
        total_net_gain=total_gain,
        marginals=marginals,
        tier_minimum_flags=flags,
    )
