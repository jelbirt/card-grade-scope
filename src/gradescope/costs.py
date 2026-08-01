"""Cost-side math: tier selection, return shipping, shared-pool amortization."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal

from gradescope.models import CostBook, ServiceLevel
from gradescope.validate import ValidationError

ZERO = Decimal(0)


def eligible_levels(book: CostBook, scenario: str, n_cards: int) -> list[ServiceLevel]:
    """Tiers orderable under the scenario whose minimum card count the batch meets."""
    return [
        lvl
        for lvl in book.orderable_levels(scenario)
        if lvl.min_cards is None or n_cards >= lvl.min_cards
    ]


def select_tier(
    book: CostBook, scenario: str, declared_value: Decimal, n_cards: int
) -> ServiceLevel:
    """Cheapest eligible tier whose max declared value covers the card (SPEC §6)."""
    candidates = [
        lvl
        for lvl in eligible_levels(book, scenario, n_cards)
        if lvl.max_declared_value >= declared_value
    ]
    if not candidates:
        raise ValidationError(
            [
                (
                    f"no eligible service level covers declared value ${declared_value} "
                    f"(scenario {scenario}, batch of {n_cards}) — cost book {book.path}"
                )
            ]
        )
    return min(candidates, key=lambda lvl: (lvl.fee_per_card, lvl.max_declared_value))


def return_shipping_fee(book: CostBook, n_items: int, insured_value: Decimal) -> Decimal:
    """Fee from PSA's chart for a submission of n_items totalling insured_value."""
    rows = [b for b in book.return_shipping if b.value_max >= insured_value]
    if not rows:
        raise ValidationError(
            [
                (
                    f"return-shipping chart has no band for insured value ${insured_value} "
                    f"— extend the cost book from its source before analyzing"
                )
            ]
        )
    value_band = min(b.value_max for b in rows)
    for band in (b for b in rows if b.value_max == value_band):
        if band.items_min <= n_items and (band.items_max is None or n_items <= band.items_max):
            if band.fee is not None:
                return band.fee
            # Open-ended row: base + per-item over the previous band's ceiling.
            return band.base_fee + band.per_item_over * (n_items - (band.items_min - 1))
    raise ValidationError(
        [f"return-shipping chart has no row for {n_items} items at value band ${value_band}"]
    )


def tax_rate_on(book: CostBook, what: str) -> Decimal:
    if book.sales_tax and what in book.sales_tax.applies_to:
        return book.sales_tax.rate
    return ZERO


SHARE_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True)
class SharedCosts:
    """The batch-shared pool S and its line items (SPEC §6: flat S/N split)."""

    lines: dict[str, Decimal] = field(default_factory=dict)

    @property
    def total(self) -> Decimal:
        return sum(self.lines.values(), ZERO)

    def share(self, n_cards: int) -> Decimal:
        return self.shares(n_cards)[0]

    def shares(self, n_cards: int) -> list[Decimal]:
        """Flat S/N split with the invariant sum(shares) == S held EXACTLY.

        S/N rarely terminates in decimal (52.99/3), so shares are floored to a
        1e-6 quantum and the remainder is distributed one quantum at a time to
        the first cards in batch order — deterministic, and off by at most a
        micro-cent per card. All cost-book amounts have <= 6 decimal places,
        so the invariant is exact.
        """
        total = self.total
        base = (total / n_cards).quantize(SHARE_QUANTUM, rounding=ROUND_FLOOR)
        remainder_quanta = int((total - base * n_cards) / SHARE_QUANTUM)
        return [base + SHARE_QUANTUM if i < remainder_quanta else base for i in range(n_cards)]


def shared_costs(
    book: CostBook,
    scenario: str,
    n_cards: int,
    total_declared: Decimal,
    tiers_used: list[ServiceLevel],
    membership_already_held: bool,
) -> SharedCosts:
    lines: dict[str, Decimal] = {}
    lines["inbound shipping + insurance"] = book.inbound_shipping.amount
    lines["return shipping + insurance"] = return_shipping_fee(book, n_cards, total_declared)
    lines["packing supplies (per submission)"] = book.supplies.per_submission
    if any(t.membership_required for t in tiers_used) and not membership_already_held:
        tier = book.cheapest_membership()
        fee = tier.annual_fee
        lines[f"Collectors Club membership ({tier.name})"] = fee
        tax = tax_rate_on(book, "membership")
        if tax:
            lines["sales tax on membership"] = fee * tax
    return SharedCosts(lines=lines)


@dataclass(frozen=True)
class CardCost:
    """C_i = f_i (per-card) + share of S. Identical across views (SPEC §6)."""

    tier: ServiceLevel
    grading_fee: Decimal
    tax_on_fee: Decimal
    supplies_per_card: Decimal
    shared_share: Decimal

    @property
    def per_card(self) -> Decimal:
        return self.grading_fee + self.tax_on_fee + self.supplies_per_card

    @property
    def total(self) -> Decimal:
        return self.per_card + self.shared_share


def card_cost(book: CostBook, tier: ServiceLevel, shared_share: Decimal) -> CardCost:
    return CardCost(
        tier=tier,
        grading_fee=tier.fee_per_card,
        tax_on_fee=tier.fee_per_card * tax_rate_on(book, "grading_fees"),
        supplies_per_card=book.supplies.per_card,
        shared_share=shared_share,
    )
