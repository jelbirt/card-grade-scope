"""Task 7: CSV bulk import — per-row errors, --strict, full-set fixtures."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from gradescope import paths
from gradescope.cli import main
from gradescope.validate import ValidationError, load_inventory, parse_import_csv

CHECKLISTS = paths.repo_root() / "data" / "sample" / "checklists"

HEADER = "id,name,set_name,card_number,variant,language,grade_low,grade_high,provenance\n"


def _write_csv(tmp_path: Path, body: str, name: str = "cards.csv", header: str = HEADER) -> Path:
    p = tmp_path / name
    p.write_text(header + body, encoding="utf-8")
    return p


def _data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


# ------------------------------------------------------------ parser rules


def test_every_error_class_reported_with_row_and_column(tmp_path):
    """One file exercising every per-row rule; all errors reported, none abort."""
    csv_file = _write_csv(
        tmp_path,
        "ok-card,Pinsir,Next Destinies,1/99,unlimited,en,7,9,pulled 1999\n"  # row 1 valid
        "Bad_Slug,Pinsir,Next Destinies,1/99,unlimited,,,,\n"  # row 2: bad slug
        ",NoId,Next Destinies,2/99,unlimited,,,,\n"  # row 3: missing id
        "ok-card,Dup,Next Destinies,3/99,unlimited,,,,\n"  # row 4: dup in file
        "bad-variant,X,Next Destinies,4/99,nonsense,,,,\n"  # row 5: unknown variant
        "bad-number,X,Next Destinies,4//99,unlimited,,,,\n"  # row 6: bad card number
        "bad-lang,X,Next Destinies,5/99,unlimited,english,,,\n"  # row 7: bad language
        "bad-range,X,Next Destinies,6/99,unlimited,,9,7,\n"  # row 8: low > high
        "half-range,X,Next Destinies,7/99,unlimited,,7,,\n"  # row 9: high missing
        "bad-int,X,Next Destinies,8/99,unlimited,,seven,9,\n"  # row 10: not an int
        "out-of-band,X,Next Destinies,9/99,unlimited,,0,9,\n"  # row 11: outside 1-10
        "short-row,X,Next Destinies\n"  # row 12: too few fields
        ",,,,,,,,\n"  # row 13: empty required fields
        "ok-card-2,Seedot,Next Destinies,2/99,unlimited,,,,\n",  # row 14 valid
    )
    result = parse_import_csv(csv_file, existing_ids=set())
    assert [c.id for c in result.cards] == ["ok-card", "ok-card-2"]
    assert result.rejected_rows == 12
    msgs = "\n".join(result.row_errors)
    assert "row 2, column id: 'Bad_Slug' must be a lowercase slug" in msgs
    assert "row 3, column id: missing required value" in msgs
    assert "row 4, column id: duplicate id 'ok-card' (earlier in this file)" in msgs
    assert "row 5, column variant: unknown variant 'nonsense'" in msgs
    assert "row 6, column card_number: '4//99' not recognized" in msgs
    assert "row 7, column language: 'english' is not ISO 639-1" in msgs
    assert "row 8, column grade_low: low 9 > high 7" in msgs
    assert "row 9, column grade_high: required when the other bound is given" in msgs
    assert "row 10, column grade_low: 'seven' is not an integer" in msgs
    assert "row 11, column grade_low: 0 outside 1-10" in msgs
    assert "row 12: expected 9 fields, got 3" in msgs
    assert "row 13, column name: missing required value" in msgs


def test_duplicate_vs_existing_inventory_rejected(tmp_path):
    csv_file = _write_csv(tmp_path, "already-here,X,S,1/99,unlimited,,,,\n")
    result = parse_import_csv(csv_file, existing_ids={"already-here"})
    assert not result.cards
    assert (
        "row 1, column id: id 'already-here' already exists in the inventory"
        in (result.row_errors[0])
    )


def test_header_problems_are_file_level(tmp_path):
    with pytest.raises(ValidationError) as exc:
        parse_import_csv(_write_csv(tmp_path, "", header="id,name,set_name\n"), set())
    assert "missing required column(s)" in str(exc.value)

    with pytest.raises(ValidationError) as exc:
        parse_import_csv(
            _write_csv(tmp_path, "", header="id,name,set_name,card_number,variant,notes\n"),
            set(),
        )
    assert "unknown column(s) ['notes']" in str(exc.value)

    with pytest.raises(ValidationError) as exc:
        parse_import_csv(
            _write_csv(tmp_path, "", header="id,id,name,set_name,card_number,variant\n"), set()
        )
    assert "duplicate column(s) ['id']" in str(exc.value)

    (tmp_path / "empty.csv").write_text("# only a comment\n", encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        parse_import_csv(tmp_path / "empty.csv", set())
    assert "empty file" in str(exc.value)


def test_comment_lines_and_optional_fields(tmp_path):
    csv_file = _write_csv(
        tmp_path,
        "full-card,Mewtwo EX,Next Destinies,98/99,full_art,en,8,10,pulled from booster\n",
        header="# source: https://example.com (accessed 2026-08-02)\n# second comment line\n"
        + "id,name,set_name,card_number,variant,language,grade_low,grade_high,provenance\n",
    )
    result = parse_import_csv(csv_file, set())
    assert result.rejected_rows == 0
    card = result.cards[0]
    assert card.estimated_grade_range == (8, 10)
    assert card.provenance == "pulled from booster"
    assert card.language == "en"


def test_condition_columns_map_to_condition_dict(tmp_path):
    header = "id,name,set_name,card_number,variant,centering,corners,condition_notes\n"
    csv_file = _write_csv(
        tmp_path,
        "cond-card,X,S,1/99,holo,60/40 front,sharp,stored in binder\n",
        header=header,
    )
    card = parse_import_csv(csv_file, set()).cards[0]
    assert card.condition == {
        "centering": "60/40 front",
        "corners": "sharp",
        "notes": "stored in binder",
    }


# ------------------------------------------------------------- cli behavior


def test_mixed_file_imports_valid_rows_and_exits_nonzero(tmp_path):
    data = _data_dir(tmp_path)
    csv_file = _write_csv(
        tmp_path,
        "good-one,X,S,1/99,unlimited,,,,\n"
        "Bad_Slug,X,S,2/99,unlimited,,,,\n"
        "good-two,X,S,3/99,unlimited,,,,\n",
    )
    result = CliRunner().invoke(main, ["import", str(csv_file), "--data-dir", str(data)])
    assert result.exit_code == 1
    assert "imported 2, rejected 1" in result.output
    assert "row 2, column id" in result.output
    inventory = load_inventory(data / "inventory.yaml")
    assert set(inventory) == {"good-one", "good-two"}


def test_strict_writes_nothing_on_any_failure(tmp_path):
    data = _data_dir(tmp_path)
    csv_file = _write_csv(
        tmp_path,
        "good-one,X,S,1/99,unlimited,,,,\nBad_Slug,X,S,2/99,unlimited,,,,\n",
    )
    result = CliRunner().invoke(
        main, ["import", str(csv_file), "--data-dir", str(data), "--strict"]
    )
    assert result.exit_code == 1
    assert "nothing imported" in result.output
    assert not (data / "inventory.yaml").exists()


def test_import_appends_without_touching_existing_content(tmp_path):
    data = _data_dir(tmp_path)
    existing = '# hand-written comment that must survive\n- id: old-card\n  name: Old\n  set_name: S\n  card_number: "1/99"\n  variant: unlimited\n'
    (data / "inventory.yaml").write_text(existing, encoding="utf-8")
    csv_file = _write_csv(tmp_path, "new-card,X,S,2/99,unlimited,,,,\n")
    result = CliRunner().invoke(main, ["import", str(csv_file), "--data-dir", str(data)])
    assert result.exit_code == 0, result.output
    text = (data / "inventory.yaml").read_text(encoding="utf-8")
    assert text.startswith(existing)  # byte-for-byte prefix preserved
    inventory = load_inventory(data / "inventory.yaml")
    assert set(inventory) == {"old-card", "new-card"}


def test_reimport_rejects_all_as_duplicates(tmp_path):
    data = _data_dir(tmp_path)
    csv_file = _write_csv(tmp_path, "one-card,X,S,1/99,unlimited,,,,\n")
    assert (
        CliRunner().invoke(main, ["import", str(csv_file), "--data-dir", str(data)]).exit_code == 0
    )
    rerun = CliRunner().invoke(main, ["import", str(csv_file), "--data-dir", str(data)])
    assert rerun.exit_code == 1
    assert "already exists in the inventory" in rerun.output
    assert "imported 0, rejected 1" in rerun.output


# ------------------------------------------------- full-set checklist fixtures


def test_full_set_fixtures_import_214_of_214(tmp_path):
    """SPEC §11.4: both complete checklists import with zero rejects, per-set
    counts reported, secret-rare numbering above set size accepted."""
    data = _data_dir(tmp_path)
    runner = CliRunner()

    nd = runner.invoke(
        main, ["import", str(CHECKLISTS / "next-destinies.csv"), "--data-dir", str(data)]
    )
    assert nd.exit_code == 0, nd.output
    assert "imported 103, rejected 0" in nd.output
    assert "Next Destinies: 103" in nd.output

    de = runner.invoke(
        main, ["import", str(CHECKLISTS / "dark-explorers.csv"), "--data-dir", str(data)]
    )
    assert de.exit_code == 0, de.output
    assert "imported 111, rejected 0" in de.output
    assert "Dark Explorers: 111" in de.output

    inventory = load_inventory(data / "inventory.yaml")
    assert len(inventory) == 214

    secret_rares = {c.card_number for c in inventory.values() if c.variant == "secret_rare"}
    assert secret_rares == {
        "100/99",
        "101/99",
        "102/99",
        "103/99",
        "109/108",
        "110/108",
        "111/108",
    }
    # spot-check the mapping of headline cards
    assert inventory["nd-098-mewtwo-ex"].variant == "full_art"
    assert inventory["de-063-darkrai-ex"].variant == "ex"
    assert inventory["de-111-pokemon-catcher"].card_number == "111/108"


def test_checklist_fixtures_cite_sources():
    """The AI-boundary rule: fixture data carries its provenance."""
    for name in ("next-destinies.csv", "dark-explorers.csv"):
        head = (CHECKLISTS / name).read_text(encoding="utf-8").splitlines()[:8]
        text = "\n".join(head)
        assert "bulbapedia.bulbagarden.net" in text
        assert "accessed 2026-08-02" in text
