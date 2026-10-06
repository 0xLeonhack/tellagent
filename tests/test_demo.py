from typer.testing import CliRunner

from tellagent.cli import app


def test_demo_command_renders_report():
    result = CliRunner().invoke(app, ["demo", "--fixture"])
    assert result.exit_code == 0
    assert "Market Contradiction Report" in result.stdout
    assert "反向证据" in result.stdout
    assert "失效条件" in result.stdout
    assert "关键指标" in result.stdout
    assert "open interest 变化 1h" in result.stdout


def test_remote_analyst_requires_configuration():
    result = CliRunner().invoke(app, ["demo", "--fixture", "--analyst", "remote"])
    assert result.exit_code == 2
    assert "TELLAGENT_MODEL_API_URL" in result.output


def test_demo_json_output_is_machine_readable():
    result = CliRunner().invoke(app, ["demo", "--fixture", "--json"])
    assert result.exit_code == 0
    assert '"asset": "BTC"' in result.stdout
    assert '"metrics"' in result.stdout
    assert "Market Contradiction Report" not in result.stdout
