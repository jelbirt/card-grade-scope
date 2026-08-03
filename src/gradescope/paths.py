"""Filesystem conventions: where data lives and which cost book is newest."""

from pathlib import Path

from gradescope.validate import ValidationError


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_config() -> Path:
    """The operator's optional engine config — untracked, machine-local (SPEC §3).

    The single seam for default-config resolution: every CLI command that
    takes --config falls back to this, and the test suite repoints it so
    tests never inherit a developer's personal config.yaml."""
    return repo_root() / "config.yaml"


def guided_priors() -> Path:
    """The guided-entry prior lookup table — shipped, committed, editable."""
    return repo_root() / "data" / "guided-priors.yaml"


def default_data_dir() -> Path:
    """Real data when present (main checkout), else the committed sample."""
    root = repo_root()
    if (root / "data" / "inventory.yaml").exists():
        return root / "data"
    return root / "data" / "sample"


def newest_cost_book(costs_dir: Path | None = None) -> Path:
    costs_dir = costs_dir or repo_root() / "data" / "costs"
    books = sorted(costs_dir.glob("psa-costs-*.yaml"))
    if not books:
        raise ValidationError([f"{costs_dir}: no cost books found (psa-costs-YYYY-MM-DD.yaml)"])
    return books[-1]
