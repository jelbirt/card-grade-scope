"""Hermeticity seams: tests must not inherit a checkout's config.yaml or real data/."""

from click.testing import CliRunner

from gradescope import paths
from gradescope.cli import main

VALID_PSA9_LINE = (
    '{"card_id": "some-card", "kind": "psa9", "value": 140.00, "currency": "USD", '
    '"source_name": "PSA APR", "source_url": "https://example.com", '
    '"date_observed": "2026-07-01"}\n'
)


def test_real_default_config_is_repo_root_config(real_default_config):
    """The shipped default stays the repo-root config.yaml (SPEC §3)."""
    assert real_default_config() == paths.repo_root() / "config.yaml"


def test_suite_is_isolated_from_local_config():
    """The autouse fixture repoints the seam at a file that never exists."""
    assert not paths.default_config().exists()


def test_cli_resolves_default_config_through_seam(tmp_path, monkeypatch):
    """A config at the seam's path takes effect without --config."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("grades: [9, 10]\n", encoding="utf-8")
    monkeypatch.setattr(paths, "default_config", lambda: cfg)
    f = tmp_path / "values.jsonl"
    f.write_text(VALID_PSA9_LINE, encoding="utf-8")  # psa9 valid under [9, 10]
    result = CliRunner().invoke(main, ["validate-snapshots", str(f)])
    assert result.exit_code == 0, result.output


def test_explicit_config_beats_default(tmp_path, monkeypatch):
    """--config wins over whatever the seam resolves to."""
    default_cfg = tmp_path / "config.yaml"
    default_cfg.write_text("grades: [9, 10]\n", encoding="utf-8")
    monkeypatch.setattr(paths, "default_config", lambda: default_cfg)
    explicit_cfg = tmp_path / "other-config.yaml"
    explicit_cfg.write_text("grades: [8, 10]\n", encoding="utf-8")  # psa9 unknown
    f = tmp_path / "values.jsonl"
    f.write_text(VALID_PSA9_LINE, encoding="utf-8")
    result = CliRunner().invoke(main, ["validate-snapshots", str(f), "--config", str(explicit_cfg)])
    assert result.exit_code == 1
    assert "unknown kind 'psa9'" in result.output


def test_real_default_data_dir_prefers_real_data(real_default_data_dir, tmp_path, monkeypatch):
    """The shipped resolver: data/ when an inventory exists there, else data/sample/."""
    monkeypatch.setattr(paths, "repo_root", lambda: tmp_path)
    (tmp_path / "data" / "sample").mkdir(parents=True)
    assert real_default_data_dir() == tmp_path / "data" / "sample"
    (tmp_path / "data" / "inventory.yaml").write_text("[]\n", encoding="utf-8")
    assert real_default_data_dir() == tmp_path / "data"


def test_suite_is_isolated_from_real_data():
    """The autouse fixture pins the data-dir seam to the committed sample."""
    assert paths.default_data_dir() == paths.repo_root() / "data" / "sample"
