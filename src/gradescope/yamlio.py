"""YAML/JSONL loading that never routes numbers through float.

SPEC hard rule: money is Decimal end-to-end; YAML floats are constructed
directly from their scalar text (Decimal("79.99")), never float(...).
"""

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml


class DecimalSafeLoader(yaml.SafeLoader):
    """SafeLoader whose float scalars become Decimal, built from the raw text."""


def _construct_decimal(loader: DecimalSafeLoader, node: yaml.ScalarNode) -> Decimal:
    text = node.value.replace("_", "")
    try:
        return Decimal(text)
    except InvalidOperation as exc:  # .inf/.nan and friends — not valid money
        raise yaml.constructor.ConstructorError(
            None, None, f"cannot represent {node.value!r} as Decimal", node.start_mark
        ) from exc


DecimalSafeLoader.add_constructor("tag:yaml.org,2002:float", _construct_decimal)


def load_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as fh:
        return yaml.load(fh, Loader=DecimalSafeLoader)


def load_jsonl(path: Path) -> list[tuple[int, object]]:
    """Parse a JSONL file to [(line_number, obj)]; floats become Decimal."""
    rows: list[tuple[int, object]] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                rows.append((lineno, json.loads(line, parse_float=Decimal)))
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {lineno}: not valid JSON ({exc.msg})") from exc
    return rows


class DecimalSafeDumper(yaml.SafeDumper):
    """SafeDumper whose Decimal values are written as plain numeric scalars
    built from their exact text — the mirror of DecimalSafeLoader."""


def _represent_decimal(dumper: DecimalSafeDumper, data: Decimal) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:float", str(data))


DecimalSafeDumper.add_representer(Decimal, _represent_decimal)


def dump_yaml(data: object) -> str:
    """Serialize for on-disk data files: key order preserved, unicode kept,
    Decimals round-tripping exactly through DecimalSafeLoader."""
    return yaml.dump(
        data,
        Dumper=DecimalSafeDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )


def dump_json_line(obj: dict) -> str:
    """One JSONL line. Decimals are emitted as their exact literal text —
    json.dumps would need float(), which is banned for money."""

    def value(v: object) -> str:
        if isinstance(v, bool) or v is None:
            raise TypeError(f"unsupported JSONL value {v!r}")
        if isinstance(v, str):
            return json.dumps(v, ensure_ascii=False)
        if isinstance(v, int | Decimal):
            return str(v)
        if isinstance(v, dict):
            return "{" + ", ".join(f"{json.dumps(str(k))}: {value(x)}" for k, x in v.items()) + "}"
        raise TypeError(f"unsupported JSONL value {v!r}")

    return value(obj) + "\n"
