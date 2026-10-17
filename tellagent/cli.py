import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
import typer

from .config import load_project_env

load_project_env()

from .agent_policy import RuleBasedAgentProvider
from .agent_provider import RemoteAgentConfig, RemoteAgentProvider
from .agent_research import AgentRequest, AgentResearchRunner
from .agent_trace import JsonlAgentTraceStore
from .analyst import RemoteAnalystConfig, generate_remote_report
from .audit import AuditReport, audit_ledger, audit_live
from .data import RollingLiveLoader
from .evaluation import evaluate_ledger, fetch_history, summarize_history
from .factors import JsonlFactorStore
from .ledger import JsonlLedger
from .memory import JsonlMemory
from .metrics import build_deterministic_report
from .observer import RemoteJevObserver, RuleBasedObserver
from .renderer import (
    render_agent_stats,
    render_audit,
    render_evaluation,
    render_reports,
    render_runtime_error,
)
from .research import replay_recorded_frames, run_research
from .review import OutcomeReviewer

app = typer.Typer(add_completion=False, help="BTC/ETH continuous market research")


@dataclass(frozen=True)
class _Pipeline:
    """Shared ledger, observer and loader wiring for both run modes."""

    observer: object
    memory: JsonlMemory
    ledger: JsonlLedger
    reviewer: OutcomeReviewer
    factor_store: JsonlFactorStore
    live_loader: RollingLiveLoader


@app.callback()
def main() -> None:
    """Run the continuous gated research pipeline."""


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
    """Workflow mode: collect real data, gate it, then call the strong analyst."""
    try:
        _validate(analyst=analyst, provider=provider)
        pipeline = _build_pipeline(memory_path, timeout, provider, interval)
        contextual_generator, report_generator = _workflow_generators(analyst)
        run_research(
            pipeline.live_loader,
            pipeline.memory,
            report_generator=report_generator,
            asset=asset,
            cycles=cycles,
            interval=interval,
            contextual_report_generator=contextual_generator,
            observer=pipeline.observer,
            ledger=pipeline.ledger,
            reviewer=pipeline.reviewer,
            factor_store=pipeline.factor_store,
            on_cycle=render_reports,
            continue_on_error=cycles == 0,
            on_error=render_runtime_error,
        )
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def agent(
    asset: Optional[str] = typer.Option(None, "--asset", help="Only research one asset, e.g. ETH."),
    cycles: int = typer.Option(0, "--cycles", min=0, help="Iterations; 0 runs until interrupted."),
    interval: float = typer.Option(300.0, "--interval", min=0.0, help="Seconds between iterations."),
    timeout: float = typer.Option(8.0, "--timeout", min=1.0, help="Public API timeout in seconds."),
    memory_path: Path = typer.Option(Path(".tellagent/memory.jsonl"), "--memory-path"),
    analyst: str = typer.Option("remote", "--analyst", help="Strong analyst: remote or none."),
    provider: str = typer.Option("rule", "--provider", help="Observer provider: rule or jev."),
    agent_provider: str = typer.Option(
        "rule", "--agent-provider", help="Agent decision provider: rule or remote."
    ),
    agent_steps: int = typer.Option(
        3, "--agent-steps", min=1, max=10, help="Maximum Agent steps per escalated frame."
    ),
    always_investigate: bool = typer.Option(
        False,
        "--always-investigate",
        help="Bypass the Gate cooldown so every frame reaches the Agent (evaluation switch).",
    ),
) -> None:
    """Agent mode: Observer → Gate → Agent actions → tools → report → trace."""
    try:
        _validate(analyst=analyst, provider=provider, agent_provider=agent_provider)
        pipeline = _build_pipeline(memory_path, timeout, provider, interval)
        runner = _build_agent_runner(
            memory_path, analyst, agent_provider, agent_steps, pipeline.factor_store
        )
        run_research(
            pipeline.live_loader,
            pipeline.memory,
            asset=asset,
            cycles=cycles,
            interval=interval,
            observer=pipeline.observer,
            ledger=pipeline.ledger,
            reviewer=pipeline.reviewer,
            factor_store=pipeline.factor_store,
            on_cycle=render_reports,
            continue_on_error=cycles == 0,
            on_error=render_runtime_error,
            agent_runner=runner,
            always_investigate=always_investigate,
        )
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def replay(
    asset: Optional[str] = typer.Option(None, "--asset", help="Only replay one asset, e.g. ETH."),
    frames: int = typer.Option(
        1, "--frames", min=1, help="How many of the most recent recorded frames to replay."
    ),
    frame_id: Optional[str] = typer.Option(
        None, "--frame-id", help="Replay one exact recorded frame instead of the newest ones."
    ),
    timeout: float = typer.Option(8.0, "--timeout", min=1.0, help="Public API timeout in seconds."),
    memory_path: Path = typer.Option(Path(".tellagent/memory.jsonl"), "--memory-path"),
    analyst: str = typer.Option("remote", "--analyst", help="Strong analyst: remote or none."),
    provider: str = typer.Option("rule", "--provider", help="Observer provider: rule or jev."),
    agent_provider: str = typer.Option(
        "rule", "--agent-provider", help="Agent decision provider: rule or remote."
    ),
    agent_steps: int = typer.Option(
        3, "--agent-steps", min=1, max=10, help="Maximum Agent steps per frame."
    ),
) -> None:
    """Replay recorded frames through the Agent without touching the ledger."""
    try:
        _validate(analyst=analyst, provider=provider, agent_provider=agent_provider)
        pipeline = _build_pipeline(memory_path, timeout, provider)
        runner = _build_agent_runner(
            memory_path, analyst, agent_provider, agent_steps, pipeline.factor_store
        )
        outcomes = replay_recorded_frames(
            pipeline.ledger,
            pipeline.memory,
            runner,
            observer=pipeline.observer,
            asset=asset,
            limit=frames,
            frame_id=frame_id,
        )
        render_reports(outcomes)
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def audit(
    asset: Optional[str] = typer.Option(None, "--asset", help="Only audit one asset, e.g. ETH."),
    limit: int = typer.Option(50, "--limit", min=1, help="Verify the most recent N frames."),
    live: bool = typer.Option(
        False, "--live", help="Also refetch public data and independently recompute every metric."
    ),
    timeout: float = typer.Option(8.0, "--timeout", min=1.0, help="Public API timeout in seconds."),
    memory_path: Path = typer.Option(Path(".tellagent/memory.jsonl"), "--memory-path"),
) -> None:
    """Verify that recorded data and judgments are real and reproducible."""
    report = audit_ledger(memory_path.parent, asset=asset, limit=limit)
    if live:
        checks = list(report.checks) + audit_live(
            asset, timeout, root=memory_path.parent, limit=limit
        )
        report = AuditReport(
            checks=checks,
            frames=report.frames,
            judgments=report.judgments,
            reproduced=report.reproduced,
            legacy_checked=report.legacy_checked,
        )
    render_audit(report)
    if not report.ok:
        raise typer.Exit(code=1)


@app.command()
def evaluate(
    days: int = typer.Option(30, "--days", min=7, max=90, help="Days of hourly history."),
    asset: Optional[str] = typer.Option(None, "--asset", help="Only evaluate one asset, e.g. BTC."),
    memory_path: Path = typer.Option(Path(".tellagent/memory.jsonl"), "--memory-path"),
    json_path: Optional[Path] = typer.Option(None, "--json", help="Write the raw measurements as JSON."),
) -> None:
    """Measure real feature distributions and compare the old and new Gate."""
    symbols = [asset.upper()] if asset else ["BTC", "ETH"]
    history = []
    try:
        for symbol in symbols:
            rows = fetch_history(symbol, days=days)
            history.append(summarize_history(symbol, rows))
    except (httpx.HTTPError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    live = [evaluate_ledger(memory_path.parent, symbol) for symbol in symbols]
    render_evaluation(history, live)
    if json_path:
        json_path.write_text(json.dumps({"history": history, "live": live}, indent=2), encoding="utf-8")


@app.command()
def agent_stats(
    asset: Optional[str] = typer.Option(None, "--asset", help="Only summarize one asset."),
    memory_path: Path = typer.Option(Path(".tellagent/memory.jsonl"), "--memory-path"),
) -> None:
    """Summarize recorded Agent runs from the replay ledger."""
    render_agent_stats(JsonlAgentTraceStore(memory_path.parent).stats(asset))


def _validate(
    analyst: str,
    provider: str,
    agent_provider: Optional[str] = None,
) -> None:
    if analyst not in {"none", "remote"}:
        raise ValueError("--analyst must be remote or none.")
    if provider not in {"rule", "jev"}:
        raise ValueError("--provider must be rule or jev.")
    if agent_provider is not None and agent_provider not in {"rule", "remote"}:
        raise ValueError("--agent-provider must be rule or remote.")


def _build_pipeline(
    memory_path: Path,
    timeout: float,
    provider: str,
    interval: float = 300.0,
) -> _Pipeline:
    observer = RuleBasedObserver() if provider == "rule" else RemoteJevObserver.from_env()
    memory = JsonlMemory(memory_path)
    ledger = JsonlLedger(memory_path.parent)
    previous_open_interest = {}
    previous_sampled_at = {}
    for frame_record in ledger.frames():
        symbol = frame_record.asset_snapshot.symbol
        value = frame_record.asset_snapshot.open_interest
        if value is not None:
            previous_open_interest[symbol] = value
            previous_sampled_at[symbol] = frame_record.frame.as_of
    return _Pipeline(
        observer=observer,
        memory=memory,
        ledger=ledger,
        reviewer=OutcomeReviewer(memory_path.parent),
        factor_store=JsonlFactorStore(memory_path.parent),
        live_loader=RollingLiveLoader(
            timeout=timeout,
            previous_open_interest=previous_open_interest,
            previous_sampled_at=previous_sampled_at,
            max_sample_gap_seconds=max(interval * 3, 600.0),
        ),
    )


def _workflow_generators(analyst: str):
    if analyst == "none":
        return (
            lambda current, item, judgment, frame, context: build_deterministic_report(
                current,
                item,
                judgment=judgment,
                assessment=frame.assessment,
            ),
            None,
        )
    config = _analyst_config(analyst)
    return (
        lambda current, item, judgment, frame, context: generate_remote_report(
            current,
            item,
            config,
            memory_context=context,
            judgment=judgment,
            assessment=frame.assessment,
        ),
        None,
    )


def _analyst_config(analyst: str) -> Optional[RemoteAnalystConfig]:
    if analyst == "none":
        return None
    try:
        return RemoteAnalystConfig.from_env()
    except ValueError as exc:
        raise ValueError(
            "{} 未配置强模型时请使用 --analyst none（确定性报告）。".format(exc)
        ) from exc


def _agent_report(request: AgentRequest, config: Optional[RemoteAnalystConfig]):
    if config is None:
        return build_deterministic_report(
            request.snapshot,
            request.asset,
            judgment=request.judgment,
            assessment=request.frame.assessment,
        )
    return generate_remote_report(
        request.snapshot,
        request.asset,
        config,
        memory_context=request.memory_context,
        judgment=request.judgment,
        assessment=request.frame.assessment,
    )


def _build_agent_runner(
    memory_path: Path,
    analyst: str,
    agent_provider: str,
    agent_steps: int,
    factor_store: JsonlFactorStore,
) -> AgentResearchRunner:
    decision_provider = _decision_provider(agent_provider, agent_steps)
    analyst_config = _analyst_config(analyst)
    return AgentResearchRunner(
        root=memory_path.parent,
        decide=decision_provider.decide,
        provider_name=decision_provider.provider,
        model_version=decision_provider.model_version,
        max_steps=agent_steps,
        report_builder=lambda request: _agent_report(request, analyst_config),
        counts_model_calls=decision_provider.counts_model_calls,
        report_counts_model_calls=analyst_config is not None,
        store=factor_store,
    )


def _decision_provider(agent_provider: str, agent_steps: int):
    if agent_provider == "remote":
        try:
            config = RemoteAgentConfig.from_env()
        except ValueError as exc:
            raise ValueError(
                "{} 未配置模型时请使用 --agent-provider rule（本地确定性策略）。".format(exc)
            ) from exc
        return RemoteAgentProvider(config)
    return RuleBasedAgentProvider(max_steps=agent_steps)


if __name__ == "__main__":
    app()
