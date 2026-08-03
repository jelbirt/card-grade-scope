"""Shared fixtures: keep the suite hermetic w.r.t. the developer's checkout."""

import pytest

from gradescope import paths

# The real resolvers, captured before the autouse fixtures below patch them,
# so tests can still assert on the unpatched resolution logic.
_real_default_config = paths.default_config
_real_default_data_dir = paths.default_data_dir


@pytest.fixture
def real_default_config():
    return _real_default_config


@pytest.fixture
def real_default_data_dir():
    return _real_default_data_dir


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
