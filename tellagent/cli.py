from pathlib import Path
from typing import Optional

import typer

from .analyst import generate_demo_report
from .data import DEFAULT_FIXTURE, load_fixture
from .renderer import render_reports

app = typer.Typer(add_completion=False, help="BTC/ETH market contradiction demo")


@app.callback()
def main() -> None:
    """Run tellagent commands."""


@app.command()
def demo(
    fixture: bool = typer.Option(True, "--fixture/--live", help="Use the offline fixture."),
    path: Optional[Path] = typer.Option(None, "--path", help="Override fixture path."),
    asset: Optional[str] = typer.Option(None, "--asset", help="Only render one asset, e.g. ETH."),
) -> None:
    if not fixture:
        raise typer.BadParameter("Live API is not implemented yet. Use --fixture for the MVP demo.")
    snapshot = load_fixture(path or DEFAULT_FIXTURE)
    selected = [item for item in snapshot.assets if not asset or item.symbol.upper() == asset.upper()]
    if not selected:
        raise typer.BadParameter("Asset not found in fixture: {}".format(asset))
    reports = [generate_demo_report(snapshot, item) for item in selected]
    render_reports(reports)
