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

# Grade outcomes are configurable data (SPEC: grade set). Labels are canonical
# strings ("7.5", "8"); outcomes below the lowest configured grade are lumped
# as "below" valued at alpha * V_raw. PSA half grades exist up to 8.5 only.
DEFAULT_GRADES = ("7.5", "8", "8.5", "9", "10")
SCENARIOS = frozenset({"current", "value_restored"})


def canon_grade(value: object) -> str:
    """Canonical grade label: 8 -> "8", Decimal("7.5") -> "7.5", "8.0" -> "8"."""
    text = str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def snapshot_kinds(grades: tuple[str, ...]) -> frozenset[str]:
    return frozenset({"raw", "pop"} | {f"psa{g}" for g in grades})


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
    """Probabilities of record for one card, keyed by canonical grade label,
    plus the lumped below-lowest-grade mass. Always validated at load: sum == 1
    within TOLERANCE, else rejected loudly (never silently normalized)."""

    by_grade: dict[str, Decimal]
    p_below: Decimal
    method: str = "manual"  # manual | guided
    date: date | None = None

    TOLERANCE = Decimal("1e-6")

    def p(self, grade: str) -> Decimal:
        return self.by_grade[grade]

    @property
    def total(self) -> Decimal:
        return sum(self.by_grade.values(), self.p_below)


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
    pop_grade: str | None = None  # canonical grade label; required when kind == "pop"


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
