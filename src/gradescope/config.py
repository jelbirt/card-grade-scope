"""Optional config.yaml overriding EngineConfig defaults (SPEC §12).

Unknown keys are rejected loudly — a typoed knob silently keeping its default
is exactly the kind of quiet wrongness this tool refuses to have.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from gradescope import yamlio
from gradescope.engine import EngineConfig
from gradescope.models import canon_grade
from gradescope.validate import ValidationError

_DECIMAL_KEYS = {"sale_friction", "alpha", "min_gain", "below_short_circuit", "prob_shift"}
_INT_KEYS = {"staleness_days"}
_TUPLE_KEYS = {"value_shocks", "cost_shocks"}
_GRADE_KEYS = {"grades"}
KNOWN_KEYS = _DECIMAL_KEYS | _INT_KEYS | _TUPLE_KEYS | _GRADE_KEYS


def load_config(path: Path | None) -> EngineConfig:
    """Defaults when path is None or missing; explicit errors otherwise."""
    if path is None or not path.exists():
        return EngineConfig()
    raw = yamlio.load_yaml(path)
    if raw is None:
        return EngineConfig()
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise ValidationError([f"{path}: top level: expected a mapping of config keys"])
    unknown = set(raw) - KNOWN_KEYS
    if unknown:
        errors.append(
            f"{path}: unknown config keys {sorted(unknown)} (known: {sorted(KNOWN_KEYS)})"
        )
    kwargs: dict = {}
    for key, value in raw.items():
        if key in _DECIMAL_KEYS:
            if isinstance(value, Decimal | int) and not isinstance(value, bool):
                kwargs[key] = Decimal(value) if isinstance(value, int) else value
            else:
                errors.append(f"{path}: {key}: expected a number, got {value!r}")
        elif key in _INT_KEYS:
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                kwargs[key] = value
            else:
                errors.append(f"{path}: {key}: expected a positive integer, got {value!r}")
        elif key in _TUPLE_KEYS:
            ok = (
                isinstance(value, list)
                and value
                and all(isinstance(v, Decimal | int) and not isinstance(v, bool) for v in value)
            )
            if ok:
                kwargs[key] = tuple(Decimal(v) if isinstance(v, int) else v for v in value)
            else:
                errors.append(f"{path}: {key}: expected a non-empty list of numbers, got {value!r}")
        elif key in _GRADE_KEYS:
            if not isinstance(value, list) or not value:
                errors.append(f"{path}: grades: expected a non-empty list of grade labels")
                continue
            labels = [canon_grade(v) for v in value]
            decimals = [Decimal(label) for label in labels]
            if len(set(labels)) != len(labels):
                errors.append(f"{path}: grades: duplicate labels in {labels}")
            elif decimals != sorted(decimals):
                errors.append(f"{path}: grades: must be ascending, got {labels}")
            elif any(d < 1 or d > 10 for d in decimals):
                errors.append(f"{path}: grades: labels must be within 1-10, got {labels}")
            else:
                kwargs[key] = tuple(labels)
    if errors:
        raise ValidationError(errors)
    config = EngineConfig(**kwargs)
    if not (0 <= config.sale_friction < 1):
        raise ValidationError([f"{path}: sale_friction must be in [0, 1)"])
    if config.alpha < 0:
        raise ValidationError([f"{path}: alpha must be >= 0"])
    return config
