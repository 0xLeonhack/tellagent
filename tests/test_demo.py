from typer.testing import CliRunner

from tellagent.cli import app


def test_demo_command_renders_report():
    result = CliRunner().invoke(app, ["demo", "--fixture"])
    assert result.exit_code == 0
    assert "Market Contradiction Report" in result.stdout
    assert "反向证据" in result.stdout
    assert "失效条件" in result.stdout
