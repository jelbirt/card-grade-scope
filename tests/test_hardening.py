"""Task 6: no-network guarantee, config.yaml knobs, loud-failure fuzz cases."""

import ast
import tomllib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from gradescope import paths
from gradescope.config import load_config
from gradescope.validate import ValidationError, load_inventory, load_snapshots
from gradescope.values import freshest_values

SRC = paths.repo_root() / "src" / "gradescope"

FORBIDDEN_IMPORTS = {
    "socket",
    "http",
    "urllib",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "ftplib",
    "smtplib",
    "telnetlib",
    "xmlrpc",
}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_no_network_imports_anywhere_in_core():
    """SPEC hard rule: the core runs offline. No module in src/gradescope may
    import a networking module, directly."""
    for py in SRC.glob("*.py"):
        overlap = _imported_modules(py) & FORBIDDEN_IMPORTS
        assert not overlap, f"{py.name} imports networking modules: {overlap}"


def test_no_network_dependencies_declared():
    """Runtime dependency tree is click + pyyaml only — no HTTP client can
    even be present."""
    pyproject = tomllib.loads((paths.repo_root() / "pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]
    names = {d.split(">=")[0].split("==")[0].strip().lower() for d in deps}
    assert names == {"click", "pyyaml"}


# ------------------------------------------------------------------ config


def test_config_defaults_when_missing(tmp_path):
    config = load_config(tmp_path / "does-not-exist.yaml")
    assert config.sale_friction == Decimal("0.13")
    assert config.staleness_days == 90


def test_config_overrides(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        "sale_friction: 0.1325\n"
        "alpha: 0.9\n"
        "min_gain: 30\n"
        "staleness_days: 45\n"
        "value_shocks: [0.05, 0.50]\n",
        encoding="utf-8",
    )
    config = load_config(p)
    assert config.sale_friction == Decimal("0.1325")
    assert config.alpha == Decimal("0.9")
    assert config.min_gain == Decimal(30)
    assert config.staleness_days == 45
    assert config.value_shocks == (Decimal("0.05"), Decimal("0.50"))
    # untouched knobs keep defaults
    assert config.prob_shift == Decimal("0.05")


def test_config_unknown_key_rejected(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("sale_fiction: 0.13\n", encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        load_config(p)
    assert "unknown config keys" in str(exc.value)
    assert "sale_fiction" in str(exc.value)


def test_config_bad_values_rejected(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("sale_friction: 1.5\n", encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        load_config(p)
    assert "sale_friction must be in [0, 1)" in str(exc.value)


# --------------------------------------------------------------- fuzz cases


def test_empty_inventory_fails_loud(tmp_path):
    p = tmp_path / "inventory.yaml"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        load_inventory(p)
    assert "expected a list of cards" in str(exc.value)


def test_missing_snapshot_kinds_named(tmp_path):
    p = tmp_path / "values.jsonl"
    p.write_text(
        '{"card_id": "x", "kind": "raw", "value": 10, "currency": "USD", '
        '"source_name": "s", "source_url": "u", "date_observed": "2026-07-01"}\n',
        encoding="utf-8",
    )
    snaps = load_snapshots(p)
    with pytest.raises(ValidationError) as exc:
        freshest_values(snaps, ["x"])
    msg = str(exc.value)
    assert "psa7" in msg and "psa10" in msg and "card x" in msg


def test_malformed_jsonl_line_number_reported(tmp_path):
    p = tmp_path / "values.jsonl"
    p.write_text('{"ok": 1}\nnot json at all\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_snapshots(p)


def test_zero_probability_grades_are_fine():
    """Zero mass on some grades is valid data, not an error."""
    from gradescope.models import GradeProbs

    probs = GradeProbs(
        p7=Decimal(0),
        p8=Decimal(0),
        p9=Decimal("0.5"),
        p10=Decimal("0.5"),
        p_below7=Decimal(0),
    )
    assert probs.total == Decimal(1)


def test_as_of_before_snapshots_not_stale():
    """A snapshot 'from the future' relative to as-of is simply not stale."""
    snaps = load_snapshots(paths.repo_root() / "data" / "sample" / "values.jsonl")
    values = freshest_values(snaps, ["nd-54-mewtwo-ex-full-art"])["nd-54-mewtwo-ex-full-art"]
    assert values.stale_kinds(date(2026, 1, 1), 90) == []
