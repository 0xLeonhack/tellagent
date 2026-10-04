from pathlib import Path
from typing import Optional

import typer

from .analyst import RemoteAnalystConfig, generate_demo_report, generate_remote_report
from .data import DEFAULT_FIXTURE, load_fixture, load_live_snapshot
from .renderer import render_json, render_reports

app = typer.Typer(add_completion=False, help="BTC/ETH market contradiction demo")


@app.callback()
def main() -> None:
    """Run tellagent commands."""


@app.command()
def demo(
    fixture: bool = typer.Option(True, "--fixture/--live", help="Use the offline fixture."),
    path: Optional[Path] = typer.Option(None, "--path", help="Override fixture path."),
    asset: Optional[str] = typer.Option(None, "--asset", help="Only render one asset, e.g. ETH."),
    timeout: float = typer.Option(8.0, "--timeout", min=1.0, help="Live API timeout in seconds."),
    analyst: str = typer.Option("demo", "--analyst", help="Analyst mode: demo or remote."),
    output_json: bool = typer.Option(False, "--json", help="Print validated reports as JSON."),
) -> None:
    if fixture and path:
        snapshot = load_fixture(path)
    elif fixture:
        snapshot = load_fixture(DEFAULT_FIXTURE)
    else:
        if path:
            raise typer.BadParameter("--path only applies to --fixture mode.")
        try:
            snapshot = load_live_snapshot(timeout=timeout)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    selected = [item for item in snapshot.assets if not asset or item.symbol.upper() == asset.upper()]
    if not selected:
        raise typer.BadParameter("Asset not found in fixture: {}".format(asset))
    if analyst not in {"demo", "remote"}:
        raise typer.BadParameter("--analyst must be demo or remote.")
    if analyst == "remote":
        try:
            config = RemoteAnalystConfig.from_env()
            reports = [generate_remote_report(snapshot, item, config) for item in selected]
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    else:
        reports = [generate_demo_report(snapshot, item) for item in selected]
    if output_json:
        typer.echo(render_json(reports))
    else:
        render_reports(reports)
