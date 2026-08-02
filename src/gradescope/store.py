"""Writing data files: append-first, rewrites only for a confirmed overwrite.

New inventory cards and probability records are appended as YAML text so the
existing file content — including hand-written comments — stays byte-for-byte
untouched. values.jsonl is append-only by SPEC §5.4 and is never rewritten
here at all. Whole-file rewrites exist solely for `add` overwriting an
existing id after explicit confirmation; they re-serialize the file and lose
comments, which the CLI warns about before writing.
"""

from pathlib import Path

from gradescope import yamlio
from gradescope.models import Card, GradeProbs, ValueSnapshot


def _append_text(path: Path, text: str) -> None:
    """Append to a file, creating it if needed, never touching existing bytes
    beyond ensuring the previous line is terminated."""
    prefix = ""
    if path.exists():
        existing = path.read_bytes()
        if existing and not existing.endswith(b"\n"):
            prefix = "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(prefix + text)


def card_to_mapping(card: Card) -> dict:
    """Card as an inventory.yaml entry (SPEC §5.1 key order, empties omitted)."""
    out: dict = {
        "id": card.id,
        "name": card.name,
        "set_name": card.set_name,
        "card_number": card.card_number,
        "variant": card.variant,
        "language": card.language,
    }
    if card.condition:
        out["condition"] = dict(card.condition)
    if card.estimated_grade_range is not None:
        out["estimated_grade_range"] = list(card.estimated_grade_range)
    if card.provenance:
        out["provenance"] = card.provenance
    if card.date_added is not None:
        out["date_added"] = card.date_added
    return out


def append_cards(path: Path, cards: list[Card]) -> None:
    _append_text(path, yamlio.dump_yaml([card_to_mapping(c) for c in cards]))


def rewrite_inventory(path: Path, cards: list[Card]) -> None:
    """Full re-serialization — only for a confirmed overwrite; comments in the
    existing file are lost."""
    path.write_text(yamlio.dump_yaml([card_to_mapping(c) for c in cards]), encoding="utf-8")


def probs_to_mapping(probs: GradeProbs) -> dict:
    out: dict = {
        "grades": dict(probs.by_grade),
        "below": probs.p_below,
        "method": probs.method,
    }
    if probs.date is not None:
        out["date"] = probs.date
    return out


def append_probability(path: Path, card_id: str, probs: GradeProbs) -> None:
    _append_text(path, yamlio.dump_yaml({card_id: probs_to_mapping(probs)}))


def rewrite_probabilities(path: Path, records: dict[str, GradeProbs]) -> None:
    """Full re-serialization — only for a confirmed overwrite."""
    path.write_text(
        yamlio.dump_yaml({cid: probs_to_mapping(p) for cid, p in records.items()}),
        encoding="utf-8",
    )


def snapshot_to_mapping(snap: ValueSnapshot) -> dict:
    """Snapshot as a values.jsonl object (SPEC §5.4), empties omitted."""
    out: dict = {
        "card_id": snap.card_id,
        "kind": snap.kind,
        "value": snap.value,
        "currency": snap.currency,
        "source_name": snap.source_name,
        "source_url": snap.source_url,
        "date_observed": snap.date_observed.isoformat(),
    }
    if snap.n_comps is not None:
        out["n_comps"] = snap.n_comps
    if snap.spread is not None:
        out["spread"] = {"low": snap.spread.low, "high": snap.spread.high}
    if snap.recorded_by:
        out["recorded_by"] = snap.recorded_by
    if snap.pop_grade is not None:
        out["pop_grade"] = snap.pop_grade
    return out


def append_snapshot(path: Path, snap: ValueSnapshot) -> None:
    """Append one validated snapshot line; existing lines are never rewritten."""
    _append_text(path, yamlio.dump_json_line(snapshot_to_mapping(snap)))
