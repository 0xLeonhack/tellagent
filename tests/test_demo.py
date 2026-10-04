from typer.testing import CliRunner

from tellagent.cli import app


def test_demo_command_renders_report():
    result = CliRunner().invoke(app, ["demo", "--fixture"])
    assert result.exit_code == 0
    assert "Market Contradiction Report" in result.stdout
    assert "反向证据" in result.stdout
    assert "失效条件" in result.stdout


def test_remote_analyst_requires_configuration():
    result = CliRunner().invoke(app, ["demo", "--fixture", "--analyst", "remote"])
    assert result.exit_code == 2
    assert "TELLAGENT_MODEL_API_URL" in result.output
