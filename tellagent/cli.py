from pathlib import Path
from typing import Optional

import typer

from .config import load_project_env

load_project_env()

from .analyst import RemoteAnalystConfig, generate_remote_report
from .data import RollingLiveLoader
from .ledger import JsonlLedger
from .factors import JsonlFactorStore
from .memory import JsonlMemory
from .metrics import build_deterministic_report
from .observer import RemoteJevObserver, RuleBasedObserver
from .renderer import render_reports
from .research import ResearchOutcome, outcome_summary, run_research
from .review import OutcomeReviewer

app = typer.Typer(add_completion=False, help="BTC/ETH continuous market research")


@app.callback()
def main() -> None:
    """Run the continuous Jev-gated research pipeline."""


@app.command()
def research(
    asset: Optional[str] = typer.Option(None, "--asset", help="Only research one asset, e.g. ETH."),
    cycles: int = typer.Option(0, "--cycles", min=0, help="Iterations; 0 runs until interrupted."),
    interval: float = typer.Option(300.0, "--interval", min=0.0, help="Seconds between iterations."),
    timeout: float = typer.Option(8.0, "--timeout", min=1.0, help="Public API timeout in seconds."),
    memory_path: Path = typer.Option(Path(".tellagent/memory.jsonl"), "--memory-path"),
    analyst: str = typer.Option("remote", "--analyst", help="Strong analyst: remote or none."),
    provider: str = typer.Option("rule", "--provider", help="Observer provider: rule or jev."),
) -> None:
    """Collect real data, let Jev gate it, then call the strong analyst."""
    try:
        if analyst not in {"none", "remote"}:
            raise ValueError("--analyst must be remote or none.")
        if provider not in {"rule", "jev"}:
            raise ValueError("--provider must be rule or jev.")
        observer = RuleBasedObserver() if provider == "rule" else RemoteJevObserver.from_env()
        contextual_generator = None
        report_generator = None
        if analyst == "remote":
            config = RemoteAnalystConfig.from_env()
            contextual_generator = lambda current, item, judgment, context: generate_remote_report(
                current, item, config, memory_context=context, judgment=judgment
            )
        else:
            report_generator = build_deterministic_report
        memory = JsonlMemory(memory_path)
        ledger = JsonlLedger(memory_path.parent)
        reviewer = OutcomeReviewer(memory_path.parent)
        factor_store = JsonlFactorStore(memory_path.parent)
        live_loader = RollingLiveLoader(timeout=timeout)

        def on_cycle(outcomes: list[ResearchOutcome]) -> None:
            render_reports(outcomes)

        run_research(
            live_loader,
            memory,
            report_generator=report_generator,
            asset=asset,
            cycles=cycles,
            interval=interval,
            contextual_report_generator=contextual_generator,
            observer=observer,
            ledger=ledger,
            reviewer=reviewer,
            factor_store=factor_store,
            on_cycle=on_cycle,
        )
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
