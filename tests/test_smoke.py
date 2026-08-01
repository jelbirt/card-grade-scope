from click.testing import CliRunner

from gradescope.cli import main


def test_cli_help_runs() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "worth grading" in result.output
