"""Task 8: guided interactive entry — scripted CliRunner sessions asserting
the exact YAML written, prior-table validation, overwrite protection."""

from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner

from gradescope import paths
from gradescope.cli import main
from gradescope.validate import (
    ValidationError,
    load_guided_priors,
    load_inventory,
    load_probabilities,
)

PRIORS = paths.repo_root() / "data" / "guided-priors.yaml"


def _data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


def _add(data: Path, input_lines: list[str]):
    return CliRunner().invoke(
        main,
        ["add", "--data-dir", str(data), "--priors", str(PRIORS)],
        input="".join(line + "\n" for line in input_lines),
    )


# A pristine card: every questionnaire answer is the best one (0 points ->
# tier 'gem-candidate'), suggestion accepted as-is.
PRISTINE_SESSION = [
    "test-mewtwo",  # id
    "Mewtwo EX",  # name
    "Next Destinies",  # set name
    "98/99",  # card number
    "full_art",  # variant
    "en",  # language (default en, typed explicitly)
    "1",  # centering: 55/45 or better (0 pts)
    "1",  # corners: all four sharp (0 pts)
    "1",  # edges: clean (0 pts)
    "1",  # surface: clean (0 pts)
    "1",  # whitening: none (0 pts)
    "stored in binder since 2012",  # condition notes
    "8 10",  # estimated grade range
    "pulled from booster",  # provenance
    "2026-08-02",  # date
    "y",  # accept suggested prior
]


# ---------------------------------------------------------------- happy path


def test_guided_session_writes_exact_yaml(tmp_path):
    data = _data_dir(tmp_path)
    result = _add(data, PRISTINE_SESSION)
    assert result.exit_code == 0, result.output
    assert "tier 'gem-candidate'" in result.output
    assert "(method: guided)" in result.output

    assert (data / "inventory.yaml").read_text(encoding="utf-8") == (
        "- id: test-mewtwo\n"
        "  name: Mewtwo EX\n"
        "  set_name: Next Destinies\n"
        "  card_number: 98/99\n"
        "  variant: full_art\n"
        "  language: en\n"
        "  condition:\n"
        "    centering: 55/45 or better\n"
        "    corners: all four sharp\n"
        "    edges: clean\n"
        "    surface: clean\n"
        "    whitening: none\n"
        "    notes: stored in binder since 2012\n"
        "  estimated_grade_range:\n"
        "  - 8\n"
        "  - 10\n"
        "  provenance: pulled from booster\n"
        "  date_added: 2026-08-02\n"
    )
    assert (data / "probabilities.yaml").read_text(encoding="utf-8") == (
        "test-mewtwo:\n"
        "  grades:\n"
        "    '7.5': 0.02\n"
        "    '8': 0.08\n"
        "    '8.5': 0.20\n"
        "    '9': 0.40\n"
        "    '10': 0.25\n"
        "  below: 0.05\n"
        "  method: guided\n"
        "  date: 2026-08-02\n"
    )
    # and the written files round-trip through the strict loaders
    inventory = load_inventory(data / "inventory.yaml")
    probs = load_probabilities(data / "probabilities.yaml")
    assert inventory["test-mewtwo"].estimated_grade_range == (8, 10)
    assert probs["test-mewtwo"].p("9") == Decimal("0.40")
    assert probs["test-mewtwo"].method == "guided"
    assert probs["test-mewtwo"].total == Decimal(1)


def test_worse_answers_select_lower_tier(tmp_path):
    data = _data_dir(tmp_path)
    session = list(PRISTINE_SESSION)
    session[0] = "test-played"
    # crease (9 pts) + heavy whitening (5 pts) -> 14 points -> catch-all tier
    session[9] = "4"  # surface: crease or deep scratch
    session[10] = "4"  # whitening: heavy
    result = _add(data, session)
    assert result.exit_code == 0, result.output
    assert "Condition points: 14 -> tier 'played'" in result.output
    probs = load_probabilities(data / "probabilities.yaml")["test-played"]
    assert probs.p_below == Decimal("0.40")
    inventory = load_inventory(data / "inventory.yaml")
    assert inventory["test-played"].condition["surface"] == "crease or deep scratch"


def test_edited_prior_recorded_as_manual_and_revalidated(tmp_path):
    """Rejecting the suggestion prompts for numbers; a set that doesn't sum
    to 1 is re-prompted (never normalized); the accepted set is method: manual."""
    data = _data_dir(tmp_path)
    session = list(PRISTINE_SESSION)
    session[0] = "test-manual"
    session[-1] = "n"  # reject the suggestion
    session += [
        # first attempt: sums to 0.95 -> re-prompted
        "0.05",
        "0.10",
        "0.20",
        "0.40",
        "0.15",
        "0.05",
        # second attempt: sums to 1
        "0.05",
        "0.10",
        "0.20",
        "0.40",
        "0.20",
        "0.05",
    ]
    result = _add(data, session)
    assert result.exit_code == 0, result.output
    assert "sum to 0.95, not 1" in result.output
    assert "(method: manual)" in result.output
    probs = load_probabilities(data / "probabilities.yaml")["test-manual"]
    assert probs.method == "manual"
    assert probs.p("10") == Decimal("0.20")
    assert probs.total == Decimal(1)


def test_append_preserves_existing_files(tmp_path):
    data = _data_dir(tmp_path)
    first = _add(data, PRISTINE_SESSION)
    assert first.exit_code == 0, first.output
    inventory_before = (data / "inventory.yaml").read_text(encoding="utf-8")

    session = list(PRISTINE_SESSION)
    session[0] = "test-second"
    second = _add(data, session)
    assert second.exit_code == 0, second.output
    text = (data / "inventory.yaml").read_text(encoding="utf-8")
    assert text.startswith(inventory_before)  # first card untouched, byte-for-byte
    assert set(load_inventory(data / "inventory.yaml")) == {"test-mewtwo", "test-second"}
    assert set(load_probabilities(data / "probabilities.yaml")) == {"test-mewtwo", "test-second"}


# ------------------------------------------------------- overwrite protection


def test_existing_id_requires_explicit_confirm(tmp_path):
    data = _data_dir(tmp_path)
    assert _add(data, PRISTINE_SESSION).exit_code == 0

    # decline the overwrite, then pick a fresh id
    session = ["test-mewtwo", "n", "test-other", *PRISTINE_SESSION[1:]]
    result = _add(data, session)
    assert result.exit_code == 0, result.output
    assert "already exists in the inventory" in result.output
    inventory = load_inventory(data / "inventory.yaml")
    assert set(inventory) == {"test-mewtwo", "test-other"}


def test_confirmed_overwrite_replaces_both_records(tmp_path):
    data = _data_dir(tmp_path)
    assert _add(data, PRISTINE_SESSION).exit_code == 0

    session = list(PRISTINE_SESSION)
    session[1:2] = ["y", "Mewtwo EX (regraded)"]  # confirm overwrite, new name
    session[10] = "4"  # surface: crease -> different tier this time (indexes shifted by the "y")
    result = _add(data, session)
    assert result.exit_code == 0, result.output
    inventory = load_inventory(data / "inventory.yaml")
    assert set(inventory) == {"test-mewtwo"}  # replaced, not duplicated
    assert inventory["test-mewtwo"].name == "Mewtwo EX (regraded)"
    probs = load_probabilities(data / "probabilities.yaml")
    assert set(probs) == {"test-mewtwo"}
    assert probs["test-mewtwo"].p_below == Decimal("0.40")  # the new tier's prior


# ------------------------------------------------------- prior-table loading


def test_shipped_prior_table_is_valid():
    table = load_guided_priors(PRIORS)
    assert [q.field for q in table.questions] == [
        "centering",
        "corners",
        "edges",
        "surface",
        "whitening",
    ]
    assert table.tiers[-1].max_points is None
    for tier in table.tiers:
        assert sum(tier.by_grade.values(), tier.p_below) == Decimal(1)
    # tier selection: boundaries inclusive, catch-all beyond
    assert table.tier_for(0).name == "gem-candidate"
    assert table.tier_for(1).name == "gem-candidate"
    assert table.tier_for(2).name == "mint-candidate"
    assert table.tier_for(8).name == "near-mint"
    assert table.tier_for(99).name == "played"


def test_prior_table_bad_sum_rejected(tmp_path):
    text = PRIORS.read_text(encoding="utf-8").replace('"10": 0.25', '"10": 0.30')
    p = tmp_path / "priors.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        load_guided_priors(p)
    assert "sums to 1.05" in str(exc.value)
    assert "never silently normalizes" in str(exc.value)


def test_prior_table_grade_set_mismatch_rejected(tmp_path):
    with pytest.raises(ValidationError) as exc:
        load_guided_priors(PRIORS, grades=("7", "8", "9", "10"))
    msg = str(exc.value)
    assert "'7.5' is not in the configured grade set" in msg
    assert "missing probability for grade(s) ['7']" in msg


def test_prior_table_structure_rejections(tmp_path):
    base = PRIORS.read_text(encoding="utf-8")

    p = tmp_path / "no-catchall.yaml"
    p.write_text(base.replace("max_points: null", "max_points: 99"), encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        load_guided_priors(p)
    assert "last tier must have max_points: null" in str(exc.value)

    p = tmp_path / "bad-points.yaml"
    p.write_text(
        base.replace('{key: "about 60/40", points: 1}', '{key: "about 60/40", points: -1}'),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError) as exc:
        load_guided_priors(p)
    assert "must be a non-negative integer" in str(exc.value)
