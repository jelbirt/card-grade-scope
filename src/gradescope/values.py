"""Snapshot selection: freshest value per (card, kind), staleness detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from gradescope.models import DEFAULT_GRADES, ValueSnapshot
from gradescope.validate import ValidationError


def value_kinds(grades: tuple[str, ...]) -> tuple[str, ...]:
    """The kinds the engine needs for every analyzed card: raw + each grade."""
    return ("raw", *(f"psa{g}" for g in grades))


@dataclass(frozen=True)
class CardValues:
    """Freshest gross values for one card, ready for the engine."""

    card_id: str
    grades: tuple[str, ...]
    by_kind: dict[str, ValueSnapshot]  # kind -> freshest snapshot

    def gross(self, kind: str) -> Decimal:
        return self.by_kind[kind].value

    def stale_kinds(self, as_of: date, staleness_days: int) -> list[str]:
        limit = timedelta(days=staleness_days)
        return [
            k for k in value_kinds(self.grades) if as_of - self.by_kind[k].date_observed > limit
        ]


def freshest_values(
    snapshots: list[ValueSnapshot],
    card_ids: list[str],
    grades: tuple[str, ...] = DEFAULT_GRADES,
) -> dict[str, CardValues]:
    """Pick the newest snapshot per (card, kind); error if any card is missing
    any of raw/psa<grade> — the engine never invents a value."""
    best: dict[tuple[str, str], ValueSnapshot] = {}
    for snap in snapshots:
        key = (snap.card_id, snap.kind)
        if key not in best or snap.date_observed > best[key].date_observed:
            best[key] = snap
    needed = value_kinds(grades)
    errors: list[str] = []
    out: dict[str, CardValues] = {}
    for cid in card_ids:
        missing = [k for k in needed if (cid, k) not in best]
        if missing:
            errors.append(
                f"card {cid}: no value snapshot for {', '.join(missing)} — record snapshots "
                "(gradescope snapshot) before analyzing this card"
            )
            continue
        out[cid] = CardValues(
            card_id=cid, grades=grades, by_kind={k: best[(cid, k)] for k in needed}
        )
    if errors:
        raise ValidationError(errors)
    return out


def freshest_values_partial(
    snapshots: list[ValueSnapshot],
    card_ids: list[str],
    grades: tuple[str, ...] = DEFAULT_GRADES,
) -> dict[str, dict[str, ValueSnapshot]]:
    """Like freshest_values but tolerant of gaps — for the plain values view,
    which shows what exists rather than demanding completeness."""
    best: dict[tuple[str, str], ValueSnapshot] = {}
    for snap in snapshots:
        key = (snap.card_id, snap.kind)
        if key not in best or snap.date_observed > best[key].date_observed:
            best[key] = snap
    needed = value_kinds(grades)
    return {cid: {k: best[(cid, k)] for k in needed if (cid, k) in best} for cid in card_ids}
