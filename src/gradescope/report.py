"""Human-readable rendering of analyses. Every number needed to recompute by
hand appears in the detail view (SPEC: no black-box verdicts)."""

from __future__ import annotations

from decimal import Decimal

from gradescope.engine import BatchAnalysis, CardAnalysis, ViewResult
from gradescope.models import GRADES

CENTS = Decimal("0.01")


def money(amount: Decimal) -> str:
    return f"${amount.quantize(CENTS)}"


VERDICT_LABEL = {"submit": "SUBMIT", "hold": "HOLD", "dont_bother": "DON'T BOTHER"}


def render_view(view: ViewResult, analysis: CardAnalysis) -> list[str]:
    p = analysis.probs
    lines = [
        f"  {view.name.replace('_', '-')} view"
        + (f" (sale friction {view.friction * 100}%)" if view.friction else " (source prices)"),
    ]
    terms = " + ".join(f"{p.p(g)}x{money(view.net_by_grade[g])}" for g in GRADES)
    lines.append(f"    EV(graded) = {terms} + {p.p_below7}x{money(view.net_below7)} [below-7]")
    lines.append(f"               = {money(view.ev_graded)}")
    lines.append(
        f"    EV(submit) = {money(view.ev_graded)} - cost {money(analysis.cost.total)}"
        f" = {money(view.ev_submit)}"
    )
    lines.append(
        f"    Net gain   = {money(view.ev_submit)} - raw {money(view.net_raw)}"
        f" = {money(view.net_gain)}"
    )
    lines.append(f"    Verdict    = {VERDICT_LABEL[view.verdict]} — {view.reason}")
    sens = view.sensitivity
    if sens is not None:
        if not sens.flips:
            lines.append(
                "    Sensitivity= robust — no tested shock (values ±25%, ±0.05 prob shifts, "
                "costs +25%) changes the verdict"
            )
        else:
            first = sens.flips[0]
            lines.append(
                f"    Sensitivity= {sens.robustness} — smallest flip: {first.description} "
                f"-> {VERDICT_LABEL[first.new_verdict]} (net gain {money(first.shocked_gain)}); "
                f"min gain under value shocks {money(sens.min_gain_under_value_shocks)}"
            )
    be = view.breakeven
    if be.kind == "threshold":
        pct = (be.p10_min * 100).quantize(Decimal("0.1"))
        lines.append(
            f"    Break-even = worth submitting only if you believe there's at least a "
            f"{pct}% chance of a PSA 10 (holding the non-top mix fixed)"
        )
    elif be.kind == "never":
        lines.append("    Break-even = never breaks even at current values and costs")
    elif be.kind == "always":
        lines.append("    Break-even = positive regardless of the PSA 10 chance")
    else:
        lines.append(
            "    Break-even = gain falls as p10 rises (PSA 10 value below the non-top mix EV) "
            "— check the value snapshots"
        )
    return lines


def render_card_detail(analysis: CardAnalysis) -> str:
    v = analysis.values
    lines = [f"=== {analysis.card_id} ==="]
    lines.append("  inputs (gross, freshest snapshot per kind):")
    for kind in ("raw", "psa7", "psa8", "psa9", "psa10"):
        snap = v.by_kind[kind]
        comps = f", n={snap.n_comps}" if snap.n_comps is not None else ""
        lines.append(
            f"    {kind:<6} {money(snap.value):>10}  ({snap.source_name}, {snap.date_observed}{comps})"
        )
    p = analysis.probs
    lines.append(
        f"  probabilities: p7={p.p7} p8={p.p8} p9={p.p9} p10={p.p10} below7={p.p_below7}"
        f" ({p.method})"
    )
    lines.append(
        f"  declared value {money(analysis.declared_value)} -> tier {analysis.cost.tier.name}"
        f" ({money(analysis.cost.grading_fee)}/card)"
    )
    if analysis.upcharge_risk:
        lines.append(
            f"  WARNING upcharge risk: PSA 10 value {money(v.gross('psa10'))} exceeds tier max "
            f"declared value {money(analysis.cost.tier.max_declared_value)}"
        )
    c = analysis.cost
    lines.append(
        f"  cost: fee {money(c.grading_fee)} + tax {money(c.tax_on_fee)}"
        f" + supplies {money(c.supplies_per_card)} + shared share {money(c.shared_share)}"
        f" = {money(c.total)}"
    )
    if analysis.stale_kinds:
        lines.append(
            f"  WARNING stale snapshots (> config days old): {', '.join(analysis.stale_kinds)}"
        )
    lines.extend(render_view(analysis.sticker, analysis))
    lines.extend(render_view(analysis.take_home, analysis))
    lines.append(
        f"  OVERALL: {VERDICT_LABEL[analysis.overall_verdict]} — {analysis.overall_reason}"
    )
    return "\n".join(lines)


CATEGORY_LABEL = {
    "standalone": "standalone-positive",
    "ride_along": "ride-along",
    "drag": "drag",
    "negative": "negative (removal doesn't help)",
}


def render_summary_table(result: BatchAnalysis) -> list[str]:
    """One line per card: everything needed to act, no detail required (SPEC §6)."""
    header = (
        f"  {'card':<32} {'verdict':<13} {'sticker':>10} {'take-home':>10} "
        f"{'BE p10':>7} {'robust':>10} flags"
    )
    lines = [header, "  " + "-" * (len(header) - 2)]
    for a in result.analyses:
        be = a.sticker.breakeven
        if be.kind == "threshold":
            be_txt = f"{(be.p10_min * 100).quantize(Decimal('0.1'))}%"
        else:
            be_txt = {"never": "never", "always": "any", "inverse": "n/a"}[be.kind]
        flags = []
        if a.stale_kinds:
            flags.append("STALE")
        if a.upcharge_risk:
            flags.append("UPCHARGE?")
        lines.append(
            f"  {a.card_id:<32} {VERDICT_LABEL[a.overall_verdict]:<13} "
            f"{money(a.sticker.net_gain):>10} {money(a.take_home.net_gain):>10} "
            f"{be_txt:>7} {a.sticker.sensitivity.robustness:>10} {' '.join(flags)}"
        )
    lines.append("  " + "-" * (len(header) - 2))
    lines.append(
        f"  {'TOTAL':<32} {'':<13} {money(result.total_net_gain['sticker']):>10} "
        f"{money(result.total_net_gain['take_home']):>10}   (batch cost {money(result.total_cost)})"
    )
    return lines


def render_batch(result: BatchAnalysis, detail: bool = True) -> str:
    """Batch report, summary first: verdict table + totals + marginal
    classification + flags; per-card detail below (nothing requires it)."""
    b = result.batch
    lines = [
        (
            f"### Batch '{b.name}' — {len(b.card_ids)} cards, scenario {b.pricing_scenario}, "
            f"membership {'already held' if b.membership_already_held else 'not held'}"
        )
    ]
    lines.extend(render_summary_table(result))
    lines.append("")
    lines.append("  shared costs (split flat across the batch):")
    for label, amount in result.shared.lines.items():
        lines.append(f"    {label}: {money(amount)}")
    lines.append(f"    total shared S = {money(result.shared.total)}")
    lines.append(f"  total batch cost: {money(result.total_cost)}")
    for view in ("sticker", "take_home"):
        lines.append(
            f"  {view.replace('_', '-')}: total EV(submit) {money(result.total_ev_submit[view])}, "
            f"total net gain {money(result.total_net_gain[view])}"
        )
    lines.append("  marginal analysis (sticker view / take-home view):")
    for m in result.marginals:
        lines.append(
            f"    {m.card_id}: {CATEGORY_LABEL[m.category['sticker']]}"
            f" / {CATEGORY_LABEL[m.category['take_home']]}"
            f"  (in-batch gain {money(m.in_batch_gain['sticker'])} / "
            f"{money(m.in_batch_gain['take_home'])}; removing it changes total net gain by "
            f"{money(m.removal_delta['sticker'])} / {money(m.removal_delta['take_home'])})"
        )
    for flag in result.tier_minimum_flags:
        lines.append(f"  NOTE: {flag}")
    if detail:
        lines.append("")
        for analysis in result.analyses:
            lines.append(render_card_detail(analysis))
            lines.append("")
    return "\n".join(lines)
