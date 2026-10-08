import sys
from pathlib import Path
from typing import Optional

import typer

from .analyst import RemoteAnalystConfig, generate_demo_report, generate_remote_report
from .data import DEFAULT_FIXTURE, SCENARIO_FIXTURES, load_fixture, load_live_snapshot
from .renderer import render_json, render_reports
from .observer import RemoteJevObserver, build_state_frame
from .research import outcome_summary, run_research
from .memory import JsonlMemory
from .stream import load_observation_snapshot, observe_snapshot, run_observer

app = typer.Typer(add_completion=False, help="BTC/ETH market contradiction demo")


@app.callback()
def main() -> None:
    """Run tellagent commands."""


@app.command()
def demo(
    fixture: bool = typer.Option(True, "--fixture/--live", help="Use the offline fixture."),
    path: Optional[Path] = typer.Option(None, "--path", help="Override fixture path."),
    scenario: str = typer.Option(
        "default", "--scenario", help="Fixture scenario: default, leverage, or spot."
    ),
    asset: Optional[str] = typer.Option(None, "--asset", help="Only render one asset, e.g. ETH."),
    timeout: float = typer.Option(8.0, "--timeout", min=1.0, help="Live API timeout in seconds."),
    analyst: str = typer.Option("demo", "--analyst", help="Analyst mode: demo or remote."),
    output_json: bool = typer.Option(False, "--json", help="Print validated reports as JSON."),
) -> None:
    try:
        if fixture:
            if path and scenario != "default":
                raise ValueError("--path and a non-default --scenario cannot be used together.")
            if scenario not in SCENARIO_FIXTURES:
                raise ValueError("--scenario must be default, leverage, or spot.")
            snapshot = load_fixture(path or SCENARIO_FIXTURES[scenario])
        else:
            if path or scenario != "default":
                raise ValueError("--path and --scenario only apply to --fixture mode.")
            snapshot = load_live_snapshot(timeout=timeout)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    selected = [item for item in snapshot.assets if not asset or item.symbol.upper() == asset.upper()]
    if not selected:
        raise typer.BadParameter("Asset not found in snapshot: {}".format(asset))
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


@app.command()
def observe(
    fixture: bool = typer.Option(True, "--fixture/--live", help="Use the offline fixture."),
    path: Optional[Path] = typer.Option(None, "--path", help="Override fixture path."),
    scenario: str = typer.Option("default", "--scenario", help="Fixture scenario."),
    asset: Optional[str] = typer.Option(None, "--asset", help="Only observe one asset."),
    cycles: int = typer.Option(1, "--cycles", min=0, help="Iterations; 0 runs until interrupted."),
    interval: float = typer.Option(300.0, "--interval", min=0.0, help="Seconds between iterations."),
    timeout: float = typer.Option(8.0, "--timeout", min=1.0, help="Live API timeout in seconds."),
    output: Optional[Path] = typer.Option(None, "--output", help="Write JSONL to a file."),
    provider: str = typer.Option("rule", "--provider", help="Observer provider: rule or jev."),
) -> None:
    """Run the Observer and emit one ContinuousJudgment JSON object per line."""
    try:
        if provider not in {"rule", "jev"}:
            raise ValueError("--provider must be rule or jev.")
        if provider == "jev":
            remote = RemoteJevObserver.from_env()
            loader = lambda: load_observation_snapshot(
                fixture=fixture, scenario=scenario, path=path, timeout=timeout
            )
            def run_remote():
                snapshot = loader()
                selected = [item for item in snapshot.assets if not asset or item.symbol.upper() == asset.upper()]
                if not selected:
                    raise ValueError("Asset not found in snapshot: {}".format(asset))
                return [remote.judge(build_state_frame(snapshot, item)) for item in selected]
            cycle_runner = run_remote
        else:
            loader = lambda: load_observation_snapshot(
            fixture=fixture, scenario=scenario, path=path, timeout=timeout
            )
            cycle_runner = lambda: observe_snapshot(loader(), asset)
        stream = output.open("a", encoding="utf-8") if output else None
        try:
            run_observer(cycle_runner, cycles=cycles, interval=interval, output=stream or sys.stdout)
        finally:
            if stream:
                stream.close()
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def research(
    fixture: bool = typer.Option(True, "--fixture/--live", help="Use the offline fixture."),
    path: Optional[Path] = typer.Option(None, "--path", help="Override fixture path."),
    scenario: str = typer.Option("default", "--scenario", help="Fixture scenario."),
    asset: Optional[str] = typer.Option(None, "--asset", help="Only research one asset."),
    timeout: float = typer.Option(8.0, "--timeout", min=1.0, help="API timeout in seconds."),
    memory_path: Path = typer.Option(Path(".tellagent/memory.jsonl"), "--memory-path"),
    analyst: str = typer.Option("none", "--analyst", help="Strong analyst: none, demo, or remote."),
    cycles: int = typer.Option(1, "--cycles", min=0, help="Iterations; 0 runs until interrupted."),
    interval: float = typer.Option(300.0, "--interval", min=0.0, help="Seconds between iterations."),
) -> None:
    """Run Jev gate and call a stronger analyst only for actionable judgments."""
    try:
        snapshot = load_observation_snapshot(
            fixture=fixture, scenario=scenario, path=path, timeout=timeout
        )
        if analyst not in {"none", "demo", "remote"}:
            raise ValueError("--analyst must be none, demo, or remote.")
        generator = None
        if analyst == "demo":
            generator = generate_demo_report
        elif analyst == "remote":
            config = RemoteAnalystConfig.from_env()
            generator = lambda current, item: generate_remote_report(current, item, config)
        memory = JsonlMemory(memory_path)
        run_research(
            lambda: load_observation_snapshot(
                fixture=fixture, scenario=scenario, path=path, timeout=timeout
            ),
            memory,
            generator,
            asset=asset,
            cycles=cycles,
            interval=interval,
            on_cycle=lambda outcomes: typer.echo(outcome_summary(outcomes)),
        )
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
