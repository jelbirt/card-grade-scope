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
            rows.append((lineno, json.loads(line, parse_float=Decimal)))
    return rows
