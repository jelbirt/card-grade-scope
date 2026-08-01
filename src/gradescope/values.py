"""Snapshot selection: freshest value per (card, kind), staleness detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from gradescope.models import ValueSnapshot
from gradescope.validate import ValidationError

VALUE_KINDS = ("raw", "psa7", "psa8", "psa9", "psa10")


@dataclass(frozen=True)
class CardValues:
    """Freshest gross values for one card, ready for the engine."""

    card_id: str
    by_kind: dict[str, ValueSnapshot]  # kind -> freshest snapshot

    def gross(self, kind: str) -> Decimal:
        return self.by_kind[kind].value

    def stale_kinds(self, as_of: date, staleness_days: int) -> list[str]:
        limit = timedelta(days=staleness_days)
        return [k for k in VALUE_KINDS if as_of - self.by_kind[k].date_observed > limit]


def freshest_values(snapshots: list[ValueSnapshot], card_ids: list[str]) -> dict[str, CardValues]:
    """Pick the newest snapshot per (card, kind); error if any card is missing
    any of raw/psa7..psa10 — the engine never invents a value."""
    best: dict[tuple[str, str], ValueSnapshot] = {}
    for snap in snapshots:
        key = (snap.card_id, snap.kind)
        if key not in best or snap.date_observed > best[key].date_observed:
            best[key] = snap
    errors: list[str] = []
    out: dict[str, CardValues] = {}
    for cid in card_ids:
        missing = [k for k in VALUE_KINDS if (cid, k) not in best]
        if missing:
            errors.append(
                f"card {cid}: no value snapshot for {', '.join(missing)} — record snapshots "
                "(gradescope snapshot) before analyzing this card"
            )
            continue
        out[cid] = CardValues(card_id=cid, by_kind={k: best[(cid, k)] for k in VALUE_KINDS})
    if errors:
        raise ValidationError(errors)
    return out
