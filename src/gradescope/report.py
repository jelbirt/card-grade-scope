"""Human-readable rendering. Every number needed to recompute by hand appears
in the detail view (SPEC: no black-box verdicts). The values table is the
tool's default face: raw + per-grade values + grading cost, no probabilities."""

from __future__ import annotations

from decimal import Decimal

from gradescope.costs import tax_rate_on
from gradescope.engine import BatchAnalysis, CardAnalysis, ViewResult
from gradescope.models import Card, CostBook, ValueSnapshot

CENTS = Decimal("0.01")


def money(amount: Decimal) -> str:
    return f"${amount.quantize(CENTS)}"


def money_signed(amount: Decimal) -> str:
    """Explicit sign for profit/loss cells: +$574.63 / -$55.37.

    Sign is decided after rounding so a sub-cent loss shows +$0.00, never a
    minus sign on a zero magnitude."""
    quantized = amount.quantize(CENTS)
    sign = "-" if quantized < 0 else "+"
    return f"{sign}${abs(quantized)}"


VERDICT_LABEL = {"submit": "SUBMIT", "hold": "HOLD", "dont_bother": "DON'T BOTHER"}


# ------------------------------------------------------------- values table


def render_values_table(
    cards: dict[str, Card],
    snapshots_by_card: dict[str, dict[str, ValueSnapshot]],
    book: CostBook,
    grades: tuple[str, ...],
    scenario: str = "current",
    verbose: bool = False,
) -> str:
    """The utility view: what's it worth raw vs at each grade, and what does
    grading cost. Needs no probabilities; missing snapshots show as '-'.

    The tier shown is the cheapest orderable tier whose max declared value
    covers the card's top-grade value (insuring for the best outcome); the
    all-in figure is that tier's fee + sales tax + per-card supplies. Shared
    per-submission costs (shipping both ways, packing) are listed once below.
    """
    top_kind = f"psa{grades[-1]}"
    tax = tax_rate_on(book, "grading_fees")
    header = f"  {'card':<32} {'raw':>9} " + " ".join(f"{'PSA ' + g:>9}" for g in grades)
    header += f"  {'tier':<12} {'all-in/card':>11}"
    lines = [header, "  " + "-" * (len(header) - 2)]
    for cid in cards:
        snaps = snapshots_by_card.get(cid, {})

        def cell(kind: str, snaps=snaps) -> str:
            return money(snaps[kind].value) if kind in snaps else "-"

        tier_txt, all_in_txt = "-", "-"
        all_in: Decimal | None = None
        if top_kind in snaps:
            from gradescope.costs import eligible_levels

            candidates = [
                lvl
                for lvl in eligible_levels(book, scenario, 1)
                if lvl.max_declared_value >= snaps[top_kind].value
            ]
            if candidates:
                tier = min(candidates, key=lambda lvl: (lvl.fee_per_card, lvl.max_declared_value))
                all_in = tier.fee_per_card * (1 + tax) + book.supplies.per_card
                tier_txt = f"{tier.name} ${tier.fee_per_card}"
                all_in_txt = money(all_in)
        row = f"  {cid:<32} {cell('raw'):>9} " + " ".join(f"{cell('psa' + g):>9}" for g in grades)
        row += f"  {tier_txt:<12} {all_in_txt:>11}"
        lines.append(row)
        # SPEC utility-first: deterministic per-grade profit/loss line — what
        # grading adds *if* the card comes back at that grade. Needs the raw
        # snapshot and a costable tier; no probabilities involved.
        if all_in is not None and "raw" in snaps:
            raw_value = snaps["raw"].value

            def profit_cell(grade: str, snaps=snaps, raw=raw_value, cost=all_in) -> str:
                kind = f"psa{grade}"
                if kind not in snaps:
                    return "-"
                return money_signed(snaps[kind].value - raw - cost)

            profit_row = f"  {'  profit/loss if graded':<32} {'':>9} " + " ".join(
                f"{profit_cell(g):>9}" for g in grades
            )
            lines.append(profit_row)
    lines.append("")
    lines.append(
        "  all-in/card = grading fee + sales tax + per-card supplies, insuring for the "
        f"PSA {grades[-1]} outcome."
    )
    lines.append(
        "  profit/loss if graded = that grade's value - raw value - all-in/card: what "
        "grading adds if the card comes back at that grade (gross sticker prices, before "
        "any seller fees)."
    )
    lines.append(
        "  Plus shared per-submission costs (split across however many cards you send): "
        f"inbound shipping {money(book.inbound_shipping.amount)}, return shipping from "
        f"{money(book.return_shipping[0].fee or Decimal(0))}, packing "
        f"{money(book.supplies.per_submission)}."
    )
    if verbose:
        lines.append("")
        lines.append("  snapshot sources:")
        for cid, snaps in snapshots_by_card.items():
            for kind, snap in snaps.items():
                comps = f", n={snap.n_comps}" if snap.n_comps is not None else ""
                lines.append(
                    f"    {cid} {kind}: {money(snap.value)} "
                    f"({snap.source_name}, {snap.date_observed}{comps}) {snap.source_url}"
                )
    return "\n".join(lines)


# ------------------------------------------------------------- card detail


def render_view(view: ViewResult, analysis: CardAnalysis, grades: tuple[str, ...]) -> list[str]:
    p = analysis.probs
    label = f" (sale friction {view.friction * 100}%)" if view.friction else " (market prices)"
    lines = [f"  {view.name.replace('_', '-')} view{label}"]
    terms = " + ".join(f"{p.p(g)}x{money(view.net_by_grade[g])}" for g in grades)
    lines.append(f"    EV(graded) = {terms} + {p.p_below}x{money(view.net_below)} [below]")
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
    top = grades[-1]
    if be.kind == "threshold":
        pct = (be.p_top_min * 100).quantize(Decimal("0.1"))
        lines.append(
            f"    Break-even = worth submitting only if you believe there's at least a "
            f"{pct}% chance of a PSA {top} (holding the non-top mix fixed)"
        )
    elif be.kind == "never":
        lines.append("    Break-even = never breaks even at current values and costs")
    elif be.kind == "always":
        lines.append(f"    Break-even = positive regardless of the PSA {top} chance")
    else:
        lines.append(
            f"    Break-even = gain falls as p{top} rises (PSA {top} value below the "
            "non-top mix EV) — check the value snapshots"
        )
    return lines


def render_card_detail(analysis: CardAnalysis) -> str:
    v = analysis.values
    grades = v.grades
    lines = [f"=== {analysis.card_id} ==="]
    lines.append("  inputs (gross, freshest snapshot per kind):")
    for kind in ("raw", *(f"psa{g}" for g in grades)):
        snap = v.by_kind[kind]
        comps = f", n={snap.n_comps}" if snap.n_comps is not None else ""
        lines.append(
            f"    {kind:<8} {money(snap.value):>10}  "
            f"({snap.source_name}, {snap.date_observed}{comps})"
        )
    p = analysis.probs
    probs_txt = " ".join(f"p{g}={p.p(g)}" for g in grades)
    lines.append(f"  probabilities: {probs_txt} below={p.p_below} ({p.method})")
    lines.append(
        f"  declared value {money(analysis.declared_value)} -> tier {analysis.cost.tier.name}"
        f" ({money(analysis.cost.grading_fee)}/card)"
    )
    if analysis.upcharge_risk:
        lines.append(
            f"  WARNING upcharge risk: PSA {grades[-1]} value "
            f"{money(v.gross(f'psa{grades[-1]}'))} exceeds tier max "
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
    for view in analysis.views:
        lines.extend(render_view(view, analysis, grades))
    lines.append(
        f"  OVERALL: {VERDICT_LABEL[analysis.overall_verdict]} — {analysis.overall_reason}"
    )
    return "\n".join(lines)


# ------------------------------------------------------------- batch report


CATEGORY_LABEL = {
    "standalone": "standalone-positive",
    "ride_along": "ride-along",
    "drag": "drag",
    "negative": "negative (removal doesn't help)",
}


def _size_shock_cell(analysis: CardAnalysis, marginal, n: int) -> str:
    """Compact N±1 column (sticker view, base-rule verdicts — the FlipPoint
    convention): 'stable', or which hypothetical batch size flips this card."""
    flipped = [
        s for s in marginal.size_shocks if s.verdict["sticker"] != analysis.sticker.base_verdict
    ]
    if not flipped:
        return "stable"
    if len(flipped) == 2:
        return "flips both"
    return "flips " + ("N-1" if flipped[0].n < n else "N+1")


def render_summary_table(result: BatchAnalysis) -> list[str]:
    """One line per card: everything needed to act, no detail required (SPEC §6)."""
    two_views = len(result.view_names) == 2
    top = result.analyses[0].values.grades[-1] if result.analyses else "top"
    n = len(result.batch.card_ids)
    marginals_by_card = {m.card_id: m for m in result.marginals}
    gain_cols = f" {'net gain':>10}" if not two_views else f" {'sticker':>10} {'take-home':>10}"
    header = (
        f"  {'card':<32} {'verdict':<13}{gain_cols} {'BE p' + top:>8} {'robust':>10}"
        f" {'N±1':>10} flags"
    )
    lines = [header, "  " + "-" * (len(header) - 2)]
    for a in result.analyses:
        be = a.sticker.breakeven
        if be.kind == "threshold":
            be_txt = f"{(be.p_top_min * 100).quantize(Decimal('0.1'))}%"
        else:
            be_txt = {"never": "never", "always": "any", "inverse": "n/a"}[be.kind]
        flags = []
        if a.stale_kinds:
            flags.append("STALE")
        if a.upcharge_risk:
            flags.append("UPCHARGE?")
        gains = f" {money(a.sticker.net_gain):>10}"
        if two_views:
            gains += f" {money(a.take_home.net_gain):>10}"
        size_txt = _size_shock_cell(a, marginals_by_card[a.card_id], n)
        lines.append(
            f"  {a.card_id:<32} {VERDICT_LABEL[a.overall_verdict]:<13}"
            f"{gains} {be_txt:>8} {a.sticker.sensitivity.robustness:>10}"
            f" {size_txt:>10} {' '.join(flags)}"
        )
    lines.append("  " + "-" * (len(header) - 2))
    totals = f" {money(result.total_net_gain['sticker']):>10}"
    if two_views:
        totals += f" {money(result.total_net_gain['take_home']):>10}"
    lines.append(f"  {'TOTAL':<32} {'':<13}{totals}   (batch cost {money(result.total_cost)})")
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
    for view in result.view_names:
        lines.append(
            f"  {view.replace('_', '-')}: total EV(submit) {money(result.total_ev_submit[view])}, "
            f"total net gain {money(result.total_net_gain[view])}"
        )
    two_views = len(result.view_names) == 2
    label = "sticker view / take-home view" if two_views else "market prices"
    lines.append(f"  marginal analysis ({label}):")
    for m in result.marginals:
        cats = CATEGORY_LABEL[m.category["sticker"]]
        gains = money(m.in_batch_gain["sticker"])
        deltas = money(m.removal_delta["sticker"])
        if two_views:
            cats += f" / {CATEGORY_LABEL[m.category['take_home']]}"
            gains += f" / {money(m.in_batch_gain['take_home'])}"
            deltas += f" / {money(m.removal_delta['take_home'])}"
        lines.append(
            f"    {m.card_id}: {cats}  (in-batch gain {gains}; "
            f"removing it changes total net gain by {deltas})"
        )
        n = len(b.card_ids)
        shock_bits = []
        if not any(s.n < n for s in m.size_shocks):
            shock_bits.append("N-1 n/a (batch of 1)")
        for s in m.size_shocks:
            verdicts = VERDICT_LABEL[s.verdict["sticker"]]
            shocked_gains = money_signed(s.gain["sticker"])
            if two_views:
                verdicts += f" / {VERDICT_LABEL[s.verdict['take_home']]}"
                shocked_gains += f" / {money_signed(s.gain['take_home'])}"
            shock_bits.append(
                f"{'N-1' if s.n < n else 'N+1'} (share {money(s.share)}): "
                f"{verdicts} ({shocked_gains})"
            )
        lines.append(f"      batch-size shock, rule verdicts: {'; '.join(shock_bits)}")
    for flag in result.tier_minimum_flags:
        lines.append(f"  NOTE: {flag}")
    if detail:
        lines.append("")
        for analysis in result.analyses:
            lines.append(render_card_detail(analysis))
            lines.append("")
    return "\n".join(lines)
