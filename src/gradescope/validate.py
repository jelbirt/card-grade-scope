"""Loading + validation of on-disk data into models.

Every rejection is explicit and names file / entry / field. Nothing is
silently normalized or skipped (SPEC hard rule).
"""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from gradescope import yamlio
from gradescope.models import (
    SCENARIOS,
    SNAPSHOT_KINDS,
    VARIANTS,
    Batch,
    Card,
    CostBook,
    CostLine,
    GradeProbs,
    MembershipTier,
    ReturnShippingBand,
    SalesTax,
    ServiceLevel,
    Source,
    Spread,
    Supplies,
    ValueSnapshot,
)

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# "4/102", "103/99" (secret rares above set size), "SM210" / "SWSH010" (promos),
# "TG01/TG30" (trainer gallery subsets)
CARD_NUMBER_RE = re.compile(r"^[A-Za-z]*\d+(/[A-Za-z]*\d+)?[A-Za-z]?$")
LANGUAGE_RE = re.compile(r"^[a-z]{2}$")


class ValidationError(Exception):
    """One or more data problems; message lists every one."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def _ctx(path: Path, where: str, msg: str) -> str:
    return f"{path}: {where}: {msg}"


def _need(mapping: dict, key: str, errors: list[str], path: Path, where: str) -> object:
    if key not in mapping or mapping[key] in (None, ""):
        errors.append(_ctx(path, where, f"missing required field '{key}'"))
        return None
    return mapping[key]


def _as_date(value: object, errors: list[str], path: Path, where: str) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        errors.append(_ctx(path, where, f"invalid date {value!r} (want YYYY-MM-DD)"))
        return None


def _as_money(value: object, errors: list[str], path: Path, where: str) -> Decimal | None:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value)
        except ArithmeticError:
            pass
    errors.append(_ctx(path, where, f"invalid number {value!r}"))
    return None


# ---------------------------------------------------------------- inventory


def load_inventory(path: Path) -> dict[str, Card]:
    raw = yamlio.load_yaml(path)
    errors: list[str] = []
    if not isinstance(raw, list):
        raise ValidationError([_ctx(path, "top level", "expected a list of cards")])
    cards: dict[str, Card] = {}
    for idx, entry in enumerate(raw):
        where = f"card[{idx}]"
        if not isinstance(entry, dict):
            errors.append(_ctx(path, where, "expected a mapping"))
            continue
        card_id = _need(entry, "id", errors, path, where)
        if card_id is not None:
            where = f"card[{idx}] (id={card_id})"
            if not ID_RE.match(str(card_id)):
                errors.append(_ctx(path, where, "id must be a lowercase slug [a-z0-9-]"))
            if card_id in cards:
                errors.append(_ctx(path, where, "duplicate card id"))
        for key in ("name", "set_name", "card_number", "variant"):
            _need(entry, key, errors, path, where)
        variant = entry.get("variant")
        if variant is not None and variant not in VARIANTS:
            errors.append(
                _ctx(path, where, f"unknown variant {variant!r} (allowed: {sorted(VARIANTS)})")
            )
        number = entry.get("card_number")
        if number is not None and not CARD_NUMBER_RE.match(str(number)):
            errors.append(
                _ctx(path, where, f"card_number {number!r} not recognized (e.g. '4/102', '103/99')")
            )
        language = entry.get("language", "en")
        if not LANGUAGE_RE.match(str(language)):
            errors.append(_ctx(path, where, f"language {language!r} is not ISO 639-1"))
        grange = entry.get("estimated_grade_range")
        grange_tuple: tuple[int, int] | None = None
        if grange is not None:
            ok = (
                isinstance(grange, list)
                and len(grange) == 2
                and all(isinstance(g, int) and 1 <= g <= 10 for g in grange)
                and grange[0] <= grange[1]
            )
            if ok:
                grange_tuple = (grange[0], grange[1])
            else:
                errors.append(
                    _ctx(
                        path, where, f"estimated_grade_range {grange!r} must be [low, high] in 1-10"
                    )
                )
        condition = entry.get("condition") or {}
        if not isinstance(condition, dict):
            errors.append(_ctx(path, where, "condition must be a mapping of free-text fields"))
            condition = {}
        added = entry.get("date_added")
        date_added = _as_date(added, errors, path, where) if added is not None else None
        if card_id is not None and not errors:
            pass  # fallthrough to construction below
        if card_id is not None and card_id not in cards:
            cards[str(card_id)] = Card(
                id=str(card_id),
                name=str(entry.get("name", "")),
                set_name=str(entry.get("set_name", "")),
                card_number=str(entry.get("card_number", "")),
                variant=str(variant) if variant else "other",
                language=str(language),
                condition={str(k): str(v) for k, v in condition.items()},
                estimated_grade_range=grange_tuple,
                provenance=str(entry.get("provenance", "")),
                date_added=date_added,
            )
    if errors:
        raise ValidationError(errors)
    return cards


# ------------------------------------------------------------- probabilities


def load_probabilities(path: Path) -> dict[str, GradeProbs]:
    raw = yamlio.load_yaml(path)
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise ValidationError([_ctx(path, "top level", "expected a mapping of card id -> probs")])
    out: dict[str, GradeProbs] = {}
    for card_id, entry in raw.items():
        where = f"probabilities for {card_id}"
        if not isinstance(entry, dict):
            errors.append(_ctx(path, where, "expected a mapping"))
            continue
        values: dict[str, Decimal] = {}
        for key in ("p7", "p8", "p9", "p10", "p_below7"):
            v = _need(entry, key, errors, path, where)
            if v is None:
                continue
            money = _as_money(v, errors, path, where)
            if money is None:
                continue
            if not (0 <= money <= 1):
                errors.append(_ctx(path, where, f"{key}={money} outside [0, 1]"))
                continue
            values[key] = money
        if len(values) != 5:
            continue
        probs = GradeProbs(
            p7=values["p7"],
            p8=values["p8"],
            p9=values["p9"],
            p10=values["p10"],
            p_below7=values["p_below7"],
            method=str(entry.get("method", "manual")),
            date=_as_date(entry["date"], errors, path, where) if entry.get("date") else None,
        )
        if abs(probs.total - 1) > GradeProbs.TOLERANCE:
            errors.append(
                _ctx(
                    path,
                    where,
                    f"probabilities sum to {probs.total}, not 1 (tolerance {GradeProbs.TOLERANCE}); "
                    "fix the numbers — this tool never silently normalizes",
                )
            )
            continue
        if probs.method not in ("manual", "guided"):
            errors.append(_ctx(path, where, f"method {probs.method!r} must be manual|guided"))
            continue
        out[str(card_id)] = probs
    if errors:
        raise ValidationError(errors)
    return out


# ----------------------------------------------------------------- snapshots


def load_snapshots(path: Path) -> list[ValueSnapshot]:
    errors: list[str] = []
    try:
        rows = yamlio.load_jsonl(path)
    except ValueError as exc:
        raise ValidationError([_ctx(path, "parse", str(exc))]) from exc
    out: list[ValueSnapshot] = []
    for lineno, obj in rows:
        where = f"line {lineno}"
        if not isinstance(obj, dict):
            errors.append(_ctx(path, where, "expected a JSON object"))
            continue
        ok = True
        for key in (
            "card_id",
            "kind",
            "value",
            "currency",
            "source_name",
            "source_url",
            "date_observed",
        ):
            if _need(obj, key, errors, path, where) is None:
                ok = False
        if not ok:
            continue
        kind = str(obj["kind"])
        if kind not in SNAPSHOT_KINDS:
            errors.append(
                _ctx(path, where, f"unknown kind {kind!r} (allowed: {sorted(SNAPSHOT_KINDS)})")
            )
            continue
        pop_grade = obj.get("pop_grade")
        if kind == "pop" and pop_grade not in (7, 8, 9, 10):
            errors.append(_ctx(path, where, "kind 'pop' requires pop_grade in 7-10"))
            continue
        value = _as_money(obj["value"], errors, path, where)
        observed = _as_date(obj["date_observed"], errors, path, where)
        if value is None or observed is None:
            continue
        spread = None
        if obj.get("spread") is not None:
            s = obj["spread"]
            low = _as_money(s.get("low"), errors, path, where) if isinstance(s, dict) else None
            high = _as_money(s.get("high"), errors, path, where) if isinstance(s, dict) else None
            if low is None or high is None or low > high:
                errors.append(_ctx(path, where, f"invalid spread {s!r} (want low <= high)"))
                continue
            spread = Spread(low=low, high=high)
        n_comps = obj.get("n_comps")
        if n_comps is not None and (not isinstance(n_comps, int) or n_comps < 0):
            errors.append(_ctx(path, where, f"n_comps {n_comps!r} must be a non-negative integer"))
            continue
        out.append(
            ValueSnapshot(
                card_id=str(obj["card_id"]),
                kind=kind,
                value=value,
                currency=str(obj["currency"]),
                source_name=str(obj["source_name"]),
                source_url=str(obj["source_url"]),
                date_observed=observed,
                n_comps=n_comps,
                spread=spread,
                recorded_by=str(obj.get("recorded_by", "")),
                pop_grade=pop_grade if kind == "pop" else None,
            )
        )
    if errors:
        raise ValidationError(errors)
    return out


# ----------------------------------------------------------------- cost book


def _as_source(obj: object, errors: list[str], path: Path, where: str) -> Source | None:
    if not isinstance(obj, dict) or "url" not in obj or "date_accessed" not in obj:
        errors.append(_ctx(path, where, "missing source {url, date_accessed}"))
        return None
    accessed = _as_date(obj["date_accessed"], errors, path, where)
    if accessed is None:
        return None
    return Source(url=str(obj["url"]), date_accessed=accessed)


def load_cost_book(path: Path) -> CostBook:
    raw = yamlio.load_yaml(path)
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise ValidationError([_ctx(path, "top level", "expected a mapping")])
    meta = raw.get("meta") or {}
    date_accessed = _as_date(meta.get("date_accessed"), errors, path, "meta")
    currency = str(meta.get("currency", "USD"))

    levels: list[ServiceLevel] = []
    for idx, entry in enumerate(raw.get("service_levels") or []):
        where = f"service_levels[{idx}]"
        name = str(entry.get("name", "")) or f"<unnamed {idx}>"
        where = f"service_levels[{idx}] ({name})"
        status = entry.get("status")
        if status not in ("active", "paused"):
            errors.append(_ctx(path, where, f"status {status!r} must be active|paused"))
            continue
        fee = _as_money(_need(entry, "fee_per_card", errors, path, where), errors, path, where)
        mdv = _as_money(
            _need(entry, "max_declared_value", errors, path, where), errors, path, where
        )
        source = _as_source(entry.get("source"), errors, path, where)
        tat = entry.get("turnaround_business_days")
        if not (isinstance(tat, list) and len(tat) == 2):
            errors.append(
                _ctx(path, where, f"turnaround_business_days {tat!r} must be [low, high]")
            )
            continue
        if fee is None or mdv is None or source is None:
            continue
        min_cards = entry.get("min_cards")
        if min_cards is not None and (not isinstance(min_cards, int) or min_cards < 1):
            errors.append(_ctx(path, where, f"min_cards {min_cards!r} must be a positive integer"))
            continue
        levels.append(
            ServiceLevel(
                name=name,
                status=str(status),
                fee_per_card=fee,
                max_declared_value=mdv,
                turnaround_business_days=(int(tat[0]), int(tat[1])),
                source=source,
                min_cards=min_cards,
                membership_required=bool(entry.get("membership_required", False)),
            )
        )

    tiers: list[MembershipTier] = []
    for idx, entry in enumerate(raw.get("membership") or []):
        where = f"membership[{idx}]"
        fee = _as_money(_need(entry, "annual_fee", errors, path, where), errors, path, where)
        source = _as_source(entry.get("source"), errors, path, where)
        if fee is None or source is None:
            continue
        tiers.append(MembershipTier(name=str(entry.get("name", "")), annual_fee=fee, source=source))

    bands: list[ReturnShippingBand] = []
    for idx, entry in enumerate(raw.get("return_shipping") or []):
        where = f"return_shipping[{idx}]"
        vmax = _as_money(_need(entry, "value_max", errors, path, where), errors, path, where)
        source = _as_source(entry.get("source"), errors, path, where)
        fee = _as_money(entry["fee"], errors, path, where) if entry.get("fee") is not None else None
        base = (
            _as_money(entry["base_fee"], errors, path, where)
            if entry.get("base_fee") is not None
            else None
        )
        per = (
            _as_money(entry["per_item_over"], errors, path, where)
            if entry.get("per_item_over") is not None
            else None
        )
        if fee is None and (base is None or per is None):
            errors.append(_ctx(path, where, "need either fee, or base_fee + per_item_over"))
            continue
        if vmax is None or source is None:
            continue
        bands.append(
            ReturnShippingBand(
                items_min=int(entry.get("items_min", 1)),
                items_max=entry.get("items_max"),
                value_max=vmax,
                source=source,
                fee=fee,
                base_fee=base,
                per_item_over=per,
            )
        )

    def cost_line(key: str) -> CostLine | None:
        entry = raw.get(key)
        where = key
        if not isinstance(entry, dict):
            errors.append(_ctx(path, where, "missing section"))
            return None
        amount = _as_money(_need(entry, "default", errors, path, where), errors, path, where)
        source = _as_source(entry.get("source"), errors, path, where)
        if amount is None or source is None:
            return None
        return CostLine(amount=amount, source=source, estimate=bool(entry.get("estimate", False)))

    inbound = cost_line("inbound_shipping")

    supplies = None
    s = raw.get("supplies")
    if isinstance(s, dict):
        per_card = _as_money(
            _need(s, "per_card", errors, path, "supplies"), errors, path, "supplies"
        )
        per_sub = _as_money(
            _need(s, "per_submission", errors, path, "supplies"), errors, path, "supplies"
        )
        source = _as_source(s.get("source"), errors, path, "supplies")
        if per_card is not None and per_sub is not None and source is not None:
            supplies = Supplies(
                per_card=per_card,
                per_submission=per_sub,
                source=source,
                estimate=bool(s.get("estimate", False)),
            )
    else:
        errors.append(_ctx(path, "supplies", "missing section"))

    tax = None
    t = raw.get("sales_tax")
    if isinstance(t, dict):
        rate = _as_money(_need(t, "rate", errors, path, "sales_tax"), errors, path, "sales_tax")
        applies_to = tuple(t.get("applies_to") or ())
        known_tax_targets = {"grading_fees", "membership"}
        unknown_targets = [a for a in applies_to if a not in known_tax_targets]
        if unknown_targets:
            errors.append(
                _ctx(
                    path,
                    "sales_tax",
                    f"unknown applies_to values {unknown_targets} "
                    f"(known: {sorted(known_tax_targets)}) — a typo here would silently "
                    "zero the tax",
                )
            )
        if rate is not None and not unknown_targets:
            tax = SalesTax(
                state=str(t.get("state", "")),
                rate=rate,
                applies_to=applies_to,
                estimate=bool(t.get("estimate", True)),
            )

    if not levels:
        errors.append(_ctx(path, "service_levels", "no valid service levels"))
    if not bands:
        errors.append(_ctx(path, "return_shipping", "no valid bands"))
    if any(lvl.membership_required for lvl in levels) and not tiers:
        errors.append(
            _ctx(
                path,
                "membership",
                "a service level requires membership but no membership tiers are defined",
            )
        )
    if errors or date_accessed is None or inbound is None or supplies is None:
        raise ValidationError(errors or [_ctx(path, "meta", "missing date_accessed")])
    return CostBook(
        date_accessed=date_accessed,
        currency=currency,
        service_levels=tuple(levels),
        membership=tuple(tiers),
        return_shipping=tuple(bands),
        inbound_shipping=inbound,
        supplies=supplies,
        sales_tax=tax,
        path=str(path),
    )


# -------------------------------------------------------------------- batch


def load_batch(path: Path, inventory: dict[str, Card]) -> Batch:
    raw = yamlio.load_yaml(path)
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise ValidationError([_ctx(path, "top level", "expected a mapping")])
    scenario = raw.get("pricing_scenario", "current")
    if scenario not in SCENARIOS:
        errors.append(
            _ctx(path, "pricing_scenario", f"{scenario!r} must be one of {sorted(SCENARIOS)}")
        )
    ids = raw.get("card_ids")
    if not isinstance(ids, list) or not ids:
        errors.append(_ctx(path, "card_ids", "expected a non-empty list"))
        ids = []
    seen: set[str] = set()
    for cid in ids:
        if cid in seen:
            errors.append(_ctx(path, "card_ids", f"duplicate card id {cid!r}"))
        seen.add(cid)
        if cid not in inventory:
            errors.append(_ctx(path, "card_ids", f"unknown card id {cid!r} (not in inventory)"))
    if errors:
        raise ValidationError(errors)
    return Batch(
        name=str(raw.get("name", path.stem)),
        pricing_scenario=str(scenario),
        membership_already_held=bool(raw.get("membership_already_held", False)),
        card_ids=tuple(str(c) for c in ids),
    )
