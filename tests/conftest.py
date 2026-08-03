"""Shared fixtures: keep the suite hermetic w.r.t. the developer's checkout."""

from pathlib import Path

import pytest

from gradescope import paths

FROZEN_COST_BOOK = Path(__file__).parent / "golden" / "fixtures" / "cost-book-frozen.yaml"

# The real resolvers, captured before the autouse fixtures below patch them,
# so tests can still assert on the unpatched resolution logic.
_real_default_config = paths.default_config
_real_default_data_dir = paths.default_data_dir
_real_newest_cost_book = paths.newest_cost_book


@pytest.fixture
def real_default_config():
    return _real_default_config


@pytest.fixture
def real_default_data_dir():
    return _real_default_data_dir


@pytest.fixture
def real_newest_cost_book():
    return _real_newest_cost_book


@pytest.fixture(autouse=True)
def _hermetic_default_config(tmp_path, monkeypatch):
    """Point default-config resolution at a nonexistent file for every test.

    Real-data checkouts carry a personal, untracked config.yaml at the repo
    root (e.g. grades: [7, 8, 9, 10]). Without this fixture, every CLI test
    that omits --config silently inherits that file, so the suite passes or
    fails depending on whose checkout it runs in. Tests that need a config
    pass --config explicitly or repoint paths.default_config themselves.
    """
    monkeypatch.setattr(paths, "default_config", lambda: tmp_path / "no-config.yaml")


@pytest.fixture(autouse=True)
def _hermetic_default_data_dir(monkeypatch):
    """Pin default-data resolution to the committed sample fixture.

    Same hermeticity hole as the config: default_data_dir() prefers data/
    whenever data/inventory.yaml exists, so in the real-data checkout every
    CLI test that omits --data-dir would read the operator's inventory and
    snapshots instead of data/sample/. Tests that need their own data dir
    pass --data-dir explicitly.
    """
    sample = paths.repo_root() / "data" / "sample"
    monkeypatch.setattr(paths, "default_data_dir", lambda: sample)


@pytest.fixture(autouse=True)
def _hermetic_newest_cost_book(monkeypatch):
    """Pin default cost-book resolution to the frozen golden fixture.

    Third hole of the same class: newest_cost_book() globs data/costs/ live,
    so an untracked draft book in a checkout (the designed refresh workflow:
    copy to a new dated file, verify, commit) changes — or, half-written,
    breaks — every CLI test that omits --cost-book. The frozen fixture is an
    exact copy of the 2026-08-01 book and is never refreshed. An explicit
    costs_dir still resolves for real, so the glob logic remains testable.
    """
    monkeypatch.setattr(
        paths,
        "newest_cost_book",
        lambda costs_dir=None: _real_newest_cost_book(costs_dir) if costs_dir else FROZEN_COST_BOOK,
    )
