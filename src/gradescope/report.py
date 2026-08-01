"""Human-readable rendering of analyses. Every number needed to recompute by
hand appears in the detail view (SPEC: no black-box verdicts)."""

from __future__ import annotations

from decimal import Decimal

from gradescope.engine import CardAnalysis, ViewResult
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
