"""The deterministic decision engine (SPEC §6). Stdlib math only.

Grade outcomes are configurable data (default 7.5/8/8.5/9/10); outcomes below
the lowest configured grade are lumped as "below" valued at alpha * V_raw.

Verdicts are sensitivity-aware: a base-rule "submit" is downgraded to "hold"
when it is not robust under the value-shock grid or when its inputs are stale.
With the default sale_friction = 0 the sticker view is the only view; setting
sale_friction > 0 adds the take-home view and the views-disagree -> hold rule.
Reasons are explicit strings so every verdict is explainable.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from gradescope.costs import CardCost, card_cost, select_tier, shared_costs
from gradescope.models import DEFAULT_GRADES, Batch, CostBook, GradeProbs
from gradescope.values import CardValues

ZERO = Decimal(0)
ONE = Decimal(1)


@dataclass(frozen=True)
class EngineConfig:
    """Knobs with SPEC §12 defaults; config.yaml overrides any of them."""

    # Jake is holding, not selling: marketplace fees are not a cost of grading.
    # For a sell-scenario analysis set e.g. 0.1325 (eBay trading-card final
    # value fee, non-store sellers) — this re-enables the take-home view.
    sale_friction: Decimal = Decimal(0)
    alpha: Decimal = Decimal("1.0")  # V_below = alpha * V_raw
    min_gain: Decimal = Decimal(20)
    below_short_circuit: Decimal = Decimal("0.5")
    staleness_days: int = 90
    # Ascending canonical grade labels; the last is the "top" outcome for
    # break-even. PSA half grades exist up to 8.5 (no PSA 9.5).
    grades: tuple[str, ...] = DEFAULT_GRADES
    # Sensitivity shocks (SPEC §6). Value shocks scale the graded-outcome
    # values only (the slab premium is the estimate most likely to be wrong);
    # V_raw and hence V_below stay fixed.
    value_shocks: tuple[Decimal, ...] = (Decimal("0.10"), Decimal("0.25"))
    prob_shift: Decimal = Decimal("0.05")
    cost_shocks: tuple[Decimal, ...] = (Decimal("0.10"), Decimal("0.25"))

    @property
    def top_grade(self) -> str:
        return self.grades[-1]


@dataclass(frozen=True)
class BreakEven:
    """Minimum top-grade mass for Net_gain >= 0, holding the relative
    proportions of all non-top outcomes (lower grades + below) fixed (SPEC §6).

    With non-top conditional EV A = (sum of non-top p * V) / (1 - p_top),
    Net_gain(t) = (1-t)*A + t*V_top - C - V_raw is linear in the top mass t:
      kind "threshold": t* = (C + V_raw - A) / (V_top - A), in (0, 1]
      kind "always":    Net_gain >= 0 even at t = 0
      kind "never":     Net_gain < 0 even at t = 1
      kind "inverse":   gain falls as p_top rises (V_top below the non-top mix
                        EV); pathological data — reported, never a threshold
    """

    kind: str  # threshold | always | never | inverse
    p_top_min: Decimal | None = None


@dataclass(frozen=True)
class FlipPoint:
    """The smallest tested perturbation in one category that changes the
    base-rule verdict (SPEC §6: flip points, not just recomputed numbers)."""

    category: str  # value | prob | cost
    description: str
    new_verdict: str
    shocked_gain: Decimal


@dataclass(frozen=True)
class ViewSensitivity:
    robustness: str  # robust | sensitive | fragile
    flips: tuple[FlipPoint, ...]
    min_gain_under_value_shocks: Decimal


@dataclass(frozen=True)
class ViewResult:
    """One internally-consistent view: sticker (friction 0) or take-home."""

    name: str  # "sticker" | "take_home"
    friction: Decimal
    net_by_grade: dict[str, Decimal]
    net_below: Decimal
    net_raw: Decimal
    ev_graded: Decimal  # sum p_g * V_g + p_below * V_below
    ev_submit: Decimal
    net_gain: Decimal
    verdict: str  # submit | hold | dont_bother (final, sensitivity-aware)
    reason: str
    breakeven: BreakEven
    base_verdict: str = ""  # rule verdict before robustness/staleness downgrades
    sensitivity: ViewSensitivity | None = None


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
    take_home: ViewResult | None  # None when sale_friction == 0 (the default)
    overall_verdict: str
    overall_reason: str
    stale_kinds: list[str]

    @property
    def views(self) -> tuple[ViewResult, ...]:
        return (self.sticker,) if self.take_home is None else (self.sticker, self.take_home)


def declared_value(probs: GradeProbs, values: CardValues, config: EngineConfig) -> Decimal:
    """Probability-weighted post-grading gross value — what you'd honestly declare."""
    graded = sum((probs.p(g) * values.gross(f"psa{g}") for g in config.grades), ZERO)
    return graded + probs.p_below * config.alpha * values.gross("raw")


def solve_breakeven(
    probs: GradeProbs,
    grades: tuple[str, ...],
    net_by_grade: dict[str, Decimal],
    net_below: Decimal,
    net_raw: Decimal,
    cost_total: Decimal,
) -> BreakEven:
    """Closed-form minimum top-grade mass (see BreakEven for the derivation)."""
    top = grades[-1]
    v_top = net_by_grade[top]
    non_top_mass = ONE - probs.p(top)
    gain_at_full_top = v_top - cost_total - net_raw
    if non_top_mass == ZERO:
        # No non-top mix to hold fixed; only the all-top endpoint is defined.
        return (
            BreakEven(kind="always", p_top_min=ZERO)
            if gain_at_full_top >= ZERO
            else BreakEven(kind="never")
        )
    non_top_ev = (
        sum((probs.p(g) * net_by_grade[g] for g in grades[:-1]), ZERO) + probs.p_below * net_below
    ) / non_top_mass
    gain_at_zero_top = non_top_ev - cost_total - net_raw
    # Gain is linear in top mass t; classify by the endpoint signs.
    if gain_at_zero_top >= ZERO and gain_at_full_top >= ZERO:
        return BreakEven(kind="always", p_top_min=ZERO)
    if gain_at_zero_top < ZERO and gain_at_full_top < ZERO:
        return BreakEven(kind="never")
    if gain_at_zero_top >= ZERO:  # positive at t=0, negative at t=1: descending
        return BreakEven(kind="inverse")
    t_star = (cost_total + net_raw - non_top_ev) / (v_top - non_top_ev)
    return BreakEven(kind="threshold", p_top_min=t_star)


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
    net_by_grade = {g: values.gross(f"psa{g}") * keep for g in config.grades}
    net_raw = values.gross("raw") * keep
    net_below = config.alpha * net_raw
    ev_graded = sum((probs.p(g) * net_by_grade[g] for g in config.grades), ZERO)
    ev_graded += probs.p_below * net_below
    ev_submit = ev_graded - cost_total
    net_gain = ev_submit - net_raw
    breakeven = solve_breakeven(probs, config.grades, net_by_grade, net_below, net_raw, cost_total)
    verdict, reason = _rule_verdict(
        net_gain, net_by_grade[config.top_grade], cost_total, probs, config, short_circuited
    )
    return ViewResult(
        name=name,
        friction=friction,
        net_by_grade=net_by_grade,
        net_below=net_below,
        net_raw=net_raw,
        ev_graded=ev_graded,
        ev_submit=ev_submit,
        net_gain=net_gain,
        verdict=verdict,
        reason=reason,
        breakeven=breakeven,
        base_verdict=verdict,
    )


def _rule_verdict(
    net_gain: Decimal,
    net_v_top: Decimal,
    cost_total: Decimal,
    probs: GradeProbs,
    config: EngineConfig,
    short_circuited: bool,
) -> tuple[str, str]:
    """The base decision rule (SPEC §6), before robustness/staleness downgrades."""
    if short_circuited:
        return (
            "dont_bother",
            (
                f"expected grade below {config.grades[0]} "
                f"(p_below={probs.p_below} >= {config.below_short_circuit})"
            ),
        )
    if net_v_top < cost_total:
        return (
            "dont_bother",
            (
                f"cost floor: even a PSA {config.top_grade} ({_fmt(net_v_top)}) is below "
                f"the cost {_fmt(cost_total)}"
            ),
        )
    if net_gain <= ZERO:
        return ("dont_bother", f"net gain {_fmt(net_gain)} is not positive")
    if net_gain < config.min_gain:
        return (
            "hold",
            f"net gain {_fmt(net_gain)} is positive but under the ${config.min_gain} threshold",
        )
    return ("submit", f"net gain {_fmt(net_gain)} clears ${config.min_gain}")


def _shocked_gain_and_verdict(
    probs: GradeProbs,
    net_by_grade: dict[str, Decimal],
    net_below: Decimal,
    net_raw: Decimal,
    cost_total: Decimal,
    config: EngineConfig,
    *,
    value_scale: Decimal = ONE,
    cost_scale: Decimal = ONE,
) -> tuple[Decimal, str]:
    """Recompute net gain and rule verdict under one shock (possibly shifted probs)."""
    graded = {g: net_by_grade[g] * value_scale for g in config.grades}
    ev = sum((probs.p(g) * graded[g] for g in config.grades), ZERO) + probs.p_below * net_below
    cost = cost_total * cost_scale
    gain = ev - cost - net_raw
    short = probs.p_below >= config.below_short_circuit
    verdict, _ = _rule_verdict(gain, graded[config.top_grade], cost, probs, config, short)
    return gain, verdict


def _adjacent_shifts(grades: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """Adjacent outcome pairs, high to low, ending at the below lump."""
    pairs = [(grades[i + 1], grades[i]) for i in range(len(grades) - 2, -1, -1)]
    pairs.append((grades[0], "below"))
    return tuple(pairs)


def _shifted_probs(probs: GradeProbs, src: str, dst: str, delta: Decimal) -> GradeProbs | None:
    """Move delta mass src -> dst; None if src lacks the mass (skip, don't clamp)."""
    p = dict(probs.by_grade)
    p["below"] = probs.p_below
    if p[src] < delta:
        return None
    p[src] -= delta
    p[dst] += delta
    below = p.pop("below")
    return GradeProbs(by_grade=p, p_below=below, method=probs.method)


def _view_sensitivity(view: ViewResult, probs: GradeProbs, config: EngineConfig) -> ViewSensitivity:
    """Shock grid for one view. Robustness labels:
    robust    — no tested shock changes the base-rule verdict
    fragile   — a 10%-magnitude shock (or a single 0.05 prob shift) flips it
    sensitive — flips somewhere between the smallest and largest shocks
    """
    cost_total = view.ev_graded - view.ev_submit
    flips: list[FlipPoint] = []
    value_gains: list[Decimal] = []
    smallest_value_shock = min(config.value_shocks)
    fragile = False

    def record(category: str, description: str, gain: Decimal, verdict: str, small: bool) -> None:
        nonlocal fragile
        if verdict != view.base_verdict:
            flips.append(
                FlipPoint(
                    category=category,
                    description=description,
                    new_verdict=verdict,
                    shocked_gain=gain,
                )
            )
            if small:
                fragile = True

    for magnitude in sorted(config.value_shocks):
        for sign in (Decimal(-1), Decimal(1)):
            scale = ONE + sign * magnitude
            gain, verdict = _shocked_gain_and_verdict(
                probs,
                view.net_by_grade,
                view.net_below,
                view.net_raw,
                cost_total,
                config,
                value_scale=scale,
            )
            value_gains.append(gain)
            pct = (sign * magnitude * 100).quantize(Decimal(1))
            record(
                "value",
                f"graded values {'+' if sign > 0 else ''}{pct}%",
                gain,
                verdict,
                small=magnitude == smallest_value_shock,
            )

    delta = config.prob_shift
    for src, dst in _adjacent_shifts(config.grades):
        for a, b in ((src, dst), (dst, src)):
            shifted = _shifted_probs(probs, a, b, delta)
            if shifted is None:
                continue
            gain, verdict = _shocked_gain_and_verdict(
                shifted,
                view.net_by_grade,
                view.net_below,
                view.net_raw,
                cost_total,
                config,
            )
            record("prob", f"shift {delta} mass {a}->{b}", gain, verdict, small=True)

    for magnitude in sorted(config.cost_shocks):
        gain, verdict = _shocked_gain_and_verdict(
            probs,
            view.net_by_grade,
            view.net_below,
            view.net_raw,
            cost_total,
            config,
            cost_scale=ONE + magnitude,
        )
        pct = (magnitude * 100).quantize(Decimal(1))
        record(
            "cost",
            f"costs +{pct}%",
            gain,
            verdict,
            small=magnitude == min(config.cost_shocks),
        )

    robustness = "robust" if not flips else ("fragile" if fragile else "sensitive")
    return ViewSensitivity(
        robustness=robustness,
        flips=tuple(flips),
        min_gain_under_value_shocks=min(value_gains) if value_gains else view.net_gain,
    )


def _finalize_view(
    view: ViewResult, probs: GradeProbs, config: EngineConfig, stale_kinds: list[str]
) -> ViewResult:
    """Apply the sensitivity-aware verdict rules (SPEC §6): a base-rule submit
    must be robust under +/-25% value shocks and free of stale inputs."""
    sens = _view_sensitivity(view, probs, config)
    verdict, reason = view.base_verdict, view.reason
    if view.base_verdict == "submit":
        if sens.min_gain_under_value_shocks <= ZERO:
            verdict = "hold"
            reason = (
                f"positive ({_fmt(view.net_gain)}) but not robust: net gain falls to "
                f"{_fmt(sens.min_gain_under_value_shocks)} within the +/-"
                f"{max(config.value_shocks) * 100}% value shocks"
            )
        elif stale_kinds:
            verdict = "hold"
            reason = (
                f"positive and robust, but stale snapshots ({', '.join(stale_kinds)}) — "
                f"refresh values older than {config.staleness_days} days before submitting"
            )
    return replace(view, verdict=verdict, reason=reason, sensitivity=sens)


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
    dv = declared_value(probs, values, config)
    tier = select_tier(book, scenario, dv, n_cards)
    cost = card_cost(book, tier, shared_share)
    short = probs.p_below >= config.below_short_circuit
    upcharge_risk = values.gross(f"psa{config.top_grade}") > tier.max_declared_value

    stale = values.stale_kinds(as_of, config.staleness_days)
    sticker = _view("sticker", ZERO, probs, values, cost.total, config, short)
    sticker = _finalize_view(sticker, probs, config, stale)
    take_home: ViewResult | None = None
    if config.sale_friction > ZERO:
        take_home = _view(
            "take_home", config.sale_friction, probs, values, cost.total, config, short
        )
        take_home = _finalize_view(take_home, probs, config, stale)

    if take_home is None or sticker.verdict == take_home.verdict:
        overall, why = sticker.verdict, sticker.reason
    else:
        overall = "hold"
        why = (
            f"views disagree (sticker: {sticker.verdict}, take-home: {take_home.verdict}) — "
            "the decision flips on marketplace fees, so it is assumption-dependent"
        )
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
    dv = declared_value(probs, values, config)
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
    total_ev_submit: dict[str, Decimal]  # per view name
    total_net_gain: dict[str, Decimal]  # per view name
    marginals: list[MarginalCard]
    tier_minimum_flags: list[str]
    view_names: tuple[str, ...]


def _active_views(config: EngineConfig) -> tuple[str, ...]:
    return ("sticker",) if config.sale_friction == ZERO else ("sticker", "take_home")


def _view_of(analysis: CardAnalysis, view: str) -> ViewResult:
    if view == "sticker":
        return analysis.sticker
    assert analysis.take_home is not None
    return analysis.take_home


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
        dv = declared_value(probs_by_card[cid], values_by_card[cid], config)
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


def _totals(
    analyses: list[CardAnalysis], views: tuple[str, ...]
) -> tuple[Decimal, dict[str, Decimal], dict[str, Decimal]]:
    total_cost = sum((a.cost.total for a in analyses), ZERO)
    ev = {v: sum((_view_of(a, v).ev_submit for a in analyses), ZERO) for v in views}
    gain = {v: sum((_view_of(a, v).net_gain for a in analyses), ZERO) for v in views}
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
    views = _active_views(config)
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
    total_cost, total_ev, total_gain = _totals(analyses, views)

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
            _, _, gain_without = _totals(without, views)
        else:
            gain_without = {v: ZERO for v in views}
        standalone_gain = {v: _view_of(standalone, v).net_gain for v in views}
        in_batch_gain = {v: _view_of(in_batch, v).net_gain for v in views}
        removal_delta = {v: gain_without[v] - total_gain[v] for v in views}
        category = {}
        for v in views:
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
        (declared_value(probs_by_card[c], values_by_card[c], config) for c in batch.card_ids),
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
        view_names=views,
    )
