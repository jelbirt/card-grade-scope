"""Task 9: snapshot entry + validate-snapshots linter."""

from decimal import Decimal
from pathlib import Path

from click.testing import CliRunner

from gradescope import paths
from gradescope.cli import main
from gradescope.validate import load_snapshots, scan_snapshots

SAMPLE_VALUES = paths.repo_root() / "data" / "sample" / "values.jsonl"

VALID_LINE = (
    '{"card_id": "some-card", "kind": "psa9", "value": 140.00, "currency": "USD", '
    '"source_name": "PSA APR", "source_url": "https://example.com", '
    '"date_observed": "2026-07-01"}\n'
)


def _data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


def _snapshot(data: Path, input_lines: list[str]):
    return CliRunner().invoke(
        main,
        ["snapshot", "--data-dir", str(data)],
        input="".join(line + "\n" for line in input_lines),
    )


SESSION = [
    "some-card",  # card id (no inventory in the data dir -> no confirm)
    "psa9",  # kind
    "140.00",  # value
    "USD",  # currency
    "eBay sold",  # source name
    "https://example.com/sold",  # source url
    "2026-08-01",  # date observed
    "6",  # n_comps
    "120",  # spread low
    "165",  # spread high
    "jake-manual",  # recorded by
]


# -------------------------------------------------------------- snapshot entry


def test_snapshot_appends_exact_line(tmp_path):
    data = _data_dir(tmp_path)
    result = _snapshot(data, SESSION)
    assert result.exit_code == 0, result.output
    assert (data / "values.jsonl").read_text(encoding="utf-8") == (
        '{"card_id": "some-card", "kind": "psa9", "value": 140.00, "currency": "USD", '
        '"source_name": "eBay sold", "source_url": "https://example.com/sold", '
        '"date_observed": "2026-08-01", "n_comps": 6, '
        '"spread": {"low": 120, "high": 165}, "recorded_by": "jake-manual"}\n'
    )
    # round-trips through the strict loader with exact Decimals
    snaps = load_snapshots(data / "values.jsonl")
    assert snaps[0].value == Decimal("140.00")
    assert snaps[0].spread.low == Decimal(120)


def test_snapshot_appends_never_rewrite_existing_lines(tmp_path):
    data = _data_dir(tmp_path)
    malformed = "not json at all\n"
    (data / "values.jsonl").write_text(VALID_LINE + malformed, encoding="utf-8")
    result = _snapshot(data, SESSION)
    assert result.exit_code == 0, result.output
    assert "line 2" in result.output and "not valid JSON" in result.output
    assert "appends never rewrite" in result.output
    text = (data / "values.jsonl").read_text(encoding="utf-8")
    assert text.startswith(VALID_LINE + malformed)  # both lines byte-for-byte intact
    assert text.count("\n") == 3


def test_snapshot_append_terminates_unterminated_last_line(tmp_path):
    data = _data_dir(tmp_path)
    (data / "values.jsonl").write_text(VALID_LINE.rstrip("\n"), encoding="utf-8")
    result = _snapshot(data, SESSION)
    assert result.exit_code == 0, result.output
    snaps = load_snapshots(data / "values.jsonl")
    assert len(snaps) == 2  # not merged into one corrupt line


def test_snapshot_pop_kind_prompts_pop_grade(tmp_path):
    data = _data_dir(tmp_path)
    session = list(SESSION)
    session[1:3] = ["pop", "10", "129"]  # kind, pop grade, population count
    session[8:10] = ["", ""]  # no spread (blank skips; second blank is unread slack)
    result = _snapshot(data, session)
    assert result.exit_code == 0, result.output
    snaps = load_snapshots(data / "values.jsonl")
    assert snaps[0].kind == "pop"
    assert snaps[0].pop_grade == "10"
    assert snaps[0].value == Decimal(129)


def test_snapshot_unknown_card_needs_confirm_when_inventory_exists(tmp_path):
    data = _data_dir(tmp_path)
    (data / "inventory.yaml").write_text(
        '- id: known-card\n  name: X\n  set_name: S\n  card_number: "1/99"\n  variant: unlimited\n',
        encoding="utf-8",
    )
    # decline for the typo'd id, then enter the known one
    session = ["typo-card", "n", "known-card", *SESSION[1:]]
    result = _snapshot(data, session)
    assert result.exit_code == 0, result.output
    assert "not in the inventory" in result.output
    assert load_snapshots(data / "values.jsonl")[0].card_id == "known-card"


# ------------------------------------------------------------------ the linter


def test_validate_snapshots_clean_file_exits_0():
    result = CliRunner().invoke(main, ["validate-snapshots", str(SAMPLE_VALUES)])
    assert result.exit_code == 0, result.output
    assert "no problems" in result.output


def test_validate_snapshots_reports_every_class_with_line_numbers(tmp_path):
    bad = tmp_path / "values.jsonl"
    bad.write_text(
        VALID_LINE  # line 1: valid
        + "{broken json\n"  # line 2: not JSON
        + '{"card_id": "x", "kind": "psa11", "value": 1, "currency": "USD", '
        '"source_name": "s", "source_url": "u", "date_observed": "2026-01-01"}\n'  # line 3
         + '{"card_id": "x", "kind": "pop", "value": 5, "currency": "USD", '
        '"source_name": "s", "source_url": "u", "date_observed": "2026-01-01"}\n'  # line 4
         + '{"card_id": "x", "kind": "raw", "value": 1, "currency": "usd", '
        '"source_name": "s", "source_url": "u", "date_observed": "2026-01-01"}\n'  # line 5
         + '{"card_id": "x", "kind": "raw", "value": 1, "currency": "USD", '
        '"source_name": "s", "source_url": "u", "date_observed": "01/02/2026"}\n'  # line 6
         + '{"card_id": "x", "kind": "raw", "currency": "USD", '
        '"source_name": "s", "source_url": "u", "date_observed": "2026-01-01"}\n'  # line 7
         + '{"card_id": "x", "kind": "raw", "value": 1, "currency": "USD", "source_name": "s", '
        '"source_url": "u", "date_observed": "2026-01-01", '
        '"spread": {"low": 9, "high": 2}}\n',  # line 8
        encoding="utf-8",
    )
    result = CliRunner().invoke(main, ["validate-snapshots", str(bad)])
    assert result.exit_code == 1
    out = result.output
    assert "line 2" in out and "not valid JSON" in out
    assert "line 3" in out and "unknown kind 'psa11'" in out
    assert "line 4" in out and "pop_grade" in out
    assert "line 5" in out and "currency 'usd'" in out
    assert "line 6" in out and "invalid date" in out
    assert "line 7" in out and "missing required field 'value'" in out
    assert "line 8" in out and "spread" in out
    assert "7 problem(s), 1 valid line(s)" in out


def test_validate_snapshots_respects_configured_grades(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("grades: [9, 10]\n", encoding="utf-8")
    f = tmp_path / "values.jsonl"
    f.write_text(VALID_LINE, encoding="utf-8")  # psa9 is valid under [9, 10]
    ok = CliRunner().invoke(main, ["validate-snapshots", str(f), "--config", str(config)])
    assert ok.exit_code == 0, ok.output

    config.write_text("grades: [8, 10]\n", encoding="utf-8")  # now psa9 is unknown
    bad = CliRunner().invoke(main, ["validate-snapshots", str(f), "--config", str(config)])
    assert bad.exit_code == 1
    assert "unknown kind 'psa9'" in bad.output


def test_scan_snapshots_never_raises_on_bad_lines(tmp_path):
    f = tmp_path / "values.jsonl"
    f.write_text("garbage\n" + VALID_LINE, encoding="utf-8")
    snaps, errors = scan_snapshots(f)
    assert len(snaps) == 1 and len(errors) == 1
    assert "line 1" in errors[0]


# ------------------------------------------------- review-pass regressions


def test_nan_and_infinity_rejected_not_crashing(tmp_path):
    """Review finding 1: NaN/Infinity parse as Decimal but poison comparisons;
    the linter must report them, never raise."""
    f = tmp_path / "values.jsonl"
    f.write_text(
        '{"card_id": "x", "kind": "raw", "value": "nan", "currency": "USD", '
        '"source_name": "s", "source_url": "u", "date_observed": "2026-01-01"}\n'
        '{"card_id": "x", "kind": "raw", "value": 1, "currency": "USD", '
        '"source_name": "s", "source_url": "u", "date_observed": "2026-01-01", '
        '"spread": {"low": "nan", "high": 5}}\n'
        '{"card_id": "x", "kind": "raw", "value": "Infinity", "currency": "USD", '
        '"source_name": "s", "source_url": "u", "date_observed": "2026-01-01"}\n',
        encoding="utf-8",
    )
    snaps, errors = scan_snapshots(f)  # must not raise
    assert not snaps
    assert len(errors) == 4  # the spread line reports both the number and the spread
    assert "line 1" in errors[0] and "invalid number" in errors[0]


def test_nan_at_value_prompt_reprompts(tmp_path):
    """Review finding 1 (prompt side): 'nan' at a money prompt re-prompts."""
    data = _data_dir(tmp_path)
    session = list(SESSION)
    session[2:3] = ["nan", "140.00"]  # bad value first, then a good one
    result = _snapshot(data, session)
    assert result.exit_code == 0, result.output
    assert "'nan' is not a number" in result.output
    assert load_snapshots(data / "values.jsonl")[0].value == Decimal("140.00")


def test_boolean_n_comps_rejected(tmp_path):
    """Review finding 2: JSON true must not pass the integer n_comps check."""
    f = tmp_path / "values.jsonl"
    f.write_text(
        VALID_LINE.replace(', "date_observed"', ', "n_comps": true, "date_observed"'),
        encoding="utf-8",
    )
    snaps, errors = scan_snapshots(f)
    assert not snaps
    assert len(errors) == 1 and "n_comps" in errors[0]
