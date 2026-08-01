"""Domain dataclasses. Loading/validation lives in validate.py; math in engine.py."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

VARIANTS = frozenset(
    {
        "first_edition_holo",
        "first_edition",
        "shadowless_holo",
        "shadowless",
        "unlimited_holo",
        "unlimited",
        "holo",
        "reverse_holo",
        "ex",
        "full_art",
        "secret_rare",
        "promo",
        "other",
    }
)

SNAPSHOT_KINDS = frozenset({"raw", "psa7", "psa8", "psa9", "psa10", "pop"})
GRADES = (7, 8, 9, 10)
SCENARIOS = frozenset({"current", "value_restored"})


@dataclass(frozen=True)
class Card:
    id: str
    name: str
    set_name: str
    card_number: str
    variant: str
    language: str = "en"
    condition: dict[str, str] = field(default_factory=dict)
    estimated_grade_range: tuple[int, int] | None = None
    provenance: str = ""
    date_added: date | None = None


@dataclass(frozen=True)
class GradeProbs:
    """Probabilities of record for one card. Always validated at load: sum == 1
    within TOLERANCE, else rejected loudly (never silently normalized)."""

    p7: Decimal
    p8: Decimal
    p9: Decimal
    p10: Decimal
    p_below7: Decimal
    method: str = "manual"  # manual | guided
    date: date | None = None

    TOLERANCE = Decimal("1e-6")

    def p(self, grade: int) -> Decimal:
        return {7: self.p7, 8: self.p8, 9: self.p9, 10: self.p10}[grade]

    @property
    def total(self) -> Decimal:
        return self.p7 + self.p8 + self.p9 + self.p10 + self.p_below7


@dataclass(frozen=True)
class Spread:
    low: Decimal
    high: Decimal


@dataclass(frozen=True)
class ValueSnapshot:
    card_id: str
    kind: str  # raw | psa7..psa10 | pop
    value: Decimal  # gross sale price; for kind=pop, the population count
    currency: str
    source_name: str
    source_url: str
    date_observed: date
    n_comps: int | None = None
    spread: Spread | None = None
    recorded_by: str = ""
    pop_grade: int | None = None  # required when kind == "pop"


@dataclass(frozen=True)
class Source:
    url: str
    date_accessed: date


@dataclass(frozen=True)
class ServiceLevel:
    name: str
    status: str  # active | paused
    fee_per_card: Decimal
    max_declared_value: Decimal
    turnaround_business_days: tuple[int, int]
    source: Source
    min_cards: int | None = None
    membership_required: bool = False


@dataclass(frozen=True)
class MembershipTier:
    name: str
    annual_fee: Decimal
    source: Source


@dataclass(frozen=True)
class ReturnShippingBand:
    """One row of PSA's return chart. Fixed-fee bands carry `fee`; the open-ended
    20+ band carries `base_fee` + `per_item_over` applied to items beyond
    `items_min - 1`."""

    items_min: int
    items_max: int | None
    value_max: Decimal
    source: Source
    fee: Decimal | None = None
    base_fee: Decimal | None = None
    per_item_over: Decimal | None = None


@dataclass(frozen=True)
class CostLine:
    amount: Decimal
    source: Source
    estimate: bool = False


@dataclass(frozen=True)
class SalesTax:
    state: str
    rate: Decimal
    applies_to: tuple[str, ...]
    estimate: bool = True


@dataclass(frozen=True)
class Supplies:
    per_card: Decimal
    per_submission: Decimal
    source: Source
    estimate: bool = True


@dataclass(frozen=True)
class CostBook:
    date_accessed: date
    currency: str
    service_levels: tuple[ServiceLevel, ...]
    membership: tuple[MembershipTier, ...]
    return_shipping: tuple[ReturnShippingBand, ...]
    inbound_shipping: CostLine
    supplies: Supplies
    sales_tax: SalesTax | None
    path: str = ""

    def level(self, name: str) -> ServiceLevel:
        for lvl in self.service_levels:
            if lvl.name == name:
                return lvl
        raise KeyError(name)

    def orderable_levels(self, scenario: str) -> tuple[ServiceLevel, ...]:
        """Tiers considered available under a pricing scenario (SPEC §5.5)."""
        if scenario == "current":
            return tuple(lvl for lvl in self.service_levels if lvl.status == "active")
        return self.service_levels

    def cheapest_membership(self) -> MembershipTier:
        return min(self.membership, key=lambda m: m.annual_fee)


@dataclass(frozen=True)
class Batch:
    name: str
    pricing_scenario: str
    membership_already_held: bool
    card_ids: tuple[str, ...]
