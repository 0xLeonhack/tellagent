from dataclasses import dataclass
import time
from typing import Callable, List, Optional

from .agent_research import AgentRequest, AgentRunOutcome
from .agent_schemas import AgentRunSummary
from .gate import evaluate_gate
from .calibration import build_strategy_thresholds, compute_feature_baselines
from .factors import JsonlFactorStore, build_factor_hypotheses
from .ledger import JsonlLedger
from .memory import JsonlMemory, memory_summary
from .observer import JudgmentProvider, RuleBasedObserver, build_state_frame
from .review import OutcomeReviewer
from .schemas import (
    AssetSnapshot,
    ContinuousJudgment,
    JudgmentTrend,
    FactorHypothesis,
    FrameLedgerRecord,
    MarketReport,
    MarketSnapshot,
    MemoryRecord,
    ResearchGuidance,
)
from .strategy import build_research_guidance
from .trends import compute_judgment_trend


ReportGenerator = Callable[[MarketSnapshot, AssetSnapshot], MarketReport]
ContextualReportGenerator = Callable[
    [MarketSnapshot, AssetSnapshot, ContinuousJudgment, str], MarketReport
]
AgentRunner = Callable[[AgentRequest], AgentRunOutcome]


@dataclass(frozen=True)
class ResearchOutcome:
    judgment: ContinuousJudgment
    trend: JudgmentTrend
    guidance: ResearchGuidance
    investigated: bool
    report: Optional[MarketReport]
    memory_record: Optional[MemoryRecord]
    factor_hypotheses: List[FactorHypothesis]
    agent_run: Optional[AgentRunSummary] = None


def process_snapshot(
    snapshot: MarketSnapshot,
    memory: JsonlMemory,
    report_generator: Optional[ReportGenerator] = None,
    asset: Optional[str] = None,
    contextual_report_generator: Optional[ContextualReportGenerator] = None,
    observer: Optional[JudgmentProvider] = None,
    ledger: Optional[JsonlLedger] = None,
    reviewer: Optional[OutcomeReviewer] = None,
    factor_store: Optional[JsonlFactorStore] = None,
    agent_runner: Optional[AgentRunner] = None,
    always_investigate: bool = False,
) -> List[ResearchOutcome]:
    """Run Observer gate, optional strong analysis, and selective memory write.

    Without ``agent_runner`` this is the deterministic workflow mode. With one,
    escalated frames are handed to a bounded Agent loop that chooses the research
    actions and may downgrade the frame to ``monitor`` or ``wait_for_confirmation``.
    """
    observer = observer or RuleBasedObserver()
    records = memory.records()
    selected = [item for item in snapshot.assets if not asset or item.symbol.upper() == asset.upper()]
    if not selected:
        raise ValueError("Asset not found in snapshot: {}".format(asset))
    outcomes = []
    for item in selected:
        historical_frames = ledger.frames(item.symbol) if ledger else []
        baseline_state = compute_feature_baselines(item, historical_frames)
        thresholds = build_strategy_thresholds(baseline_state)
        if thresholds:
            item = item.model_copy(update={"strategy_thresholds": thresholds})
        frame = build_state_frame(snapshot, item, baseline_state)
        if ledger:
            ledger.append_frame(snapshot, item, frame)
            judgment_history = ledger.judgments(item.symbol)
            previous = judgment_history[-1] if judgment_history else None
        else:
            judgment_history = [record.judgment for record in records if record.asset.upper() == item.symbol.upper()]
            previous = _latest_judgment(records, item.symbol)
        judgment = observer.judge(frame)
        trend = compute_judgment_trend(judgment, judgment_history)
        guidance = build_research_guidance(judgment)
        if ledger:
            ledger.append_judgment(judgment)
        gate_decision = evaluate_gate(
            judgment, previous, event_open=previous is not None, trend=trend
        )
        investigate = gate_decision.action in {"open_event", "update_event"}
        gate_reason = gate_decision.reason
        if always_investigate and agent_runner is not None:
            # Evaluation switch: skip the Gate cooldown so every frame reaches the
            # Agent. The Agent still decides on its own whether to report.
            investigate = True
            gate_reason = "gate bypassed: every frame is handed to the Agent"
        report = None
        agent_run = None
        factor_hypotheses = []
        if investigate:
            related_context = memory_summary(
                memory.related(item.symbol, state=judgment.selected_value, tags=judgment.contradicting_roles)
            )
            if agent_runner is not None:
                agent_outcome = agent_runner(AgentRequest(
                    snapshot=snapshot,
                    asset=item,
                    frame=frame,
                    judgment=judgment,
                    trend=trend,
                    guidance=guidance,
                    memory_context=related_context,
                    gate_reason=gate_reason,
                ))
                agent_run = agent_outcome.summary
                report = agent_outcome.report
                factor_hypotheses = agent_outcome.factor_hypotheses
                # The Agent may downgrade an escalated frame to monitor or
                # wait_for_confirmation; then no report and no memory are written.
                investigate = agent_outcome.escalated
            elif contextual_report_generator:
                report = contextual_report_generator(snapshot, item, judgment, related_context)
            elif report_generator:
                report = report_generator(snapshot, item)
        summary = report.headline if report else "{}: {}".format(judgment.selected_value, judgment.research_priority)
        memory_record = None
        if investigate:
            memory_record = memory.append(
                judgment,
                summary,
                tags=[judgment.selected_value, judgment.research_priority] + judgment.contradicting_roles,
                report=report,
            )
            records.append(memory_record)
            if reviewer:
                reviewer.open_event(snapshot, item, frame, judgment, report)
            if agent_runner is None:
                # Workflow mode derives factor hypotheses from the fixed state mapping;
                # agent mode already wrote them through the create_factor_hypothesis tool.
                factor_hypotheses = build_factor_hypotheses(judgment, guidance, report)
                if factor_store:
                    for hypothesis in factor_hypotheses:
                        factor_store.append_hypothesis(hypothesis)
        outcomes.append(ResearchOutcome(
            judgment, trend, guidance, investigate, report, memory_record,
            factor_hypotheses, agent_run,
        ))
    return outcomes


def replay_recorded_frames(
    ledger: JsonlLedger,
    memory: JsonlMemory,
    agent_runner: AgentRunner,
    observer: Optional[JudgmentProvider] = None,
    asset: Optional[str] = None,
    limit: int = 1,
    frame_id: Optional[str] = None,
) -> List[ResearchOutcome]:
    """Re-run the Agent over frames already recorded in the ledger.

    Facts are never re-fetched and nothing is rewritten: the frame is rebuilt from
    its own point-in-time record, the Observer re-judges it deterministically, and
    the tools are cut off at the frame's ``as_of`` so the replay cannot see
    anything that happened later. Only a new trace (and any factor hypothesis the
    Agent creates) is appended.
    """
    if limit < 1:
        raise ValueError("replay limit must be at least 1")
    observer = observer or RuleBasedObserver()
    records = ledger.frames(asset)
    if not records:
        raise ValueError("No recorded frames to replay; run `research` or `agent` first.")
    if frame_id:
        records = [record for record in records if record.record_id == frame_id]
        if not records:
            raise ValueError("No recorded frame with id {}".format(frame_id))
    else:
        records = records[-limit:]
    outcomes = []
    for record in records:
        snapshot = snapshot_from_record(record)
        item = record.asset_snapshot
        frame = build_state_frame(snapshot, item, record.frame.baseline_state)
        judgment_history = [
            item_judgment
            for item_judgment in ledger.judgments(frame.asset)
            if item_judgment.as_of < frame.as_of
        ]
        judgment = observer.judge(frame)
        trend = compute_judgment_trend(judgment, judgment_history)
        guidance = build_research_guidance(judgment)
        related_context = memory_summary(
            memory.related(item.symbol, state=judgment.selected_value, tags=judgment.contradicting_roles)
        )
        agent_outcome = agent_runner(AgentRequest(
            snapshot=snapshot,
            asset=item,
            frame=frame,
            judgment=judgment,
            trend=trend,
            guidance=guidance,
            memory_context=related_context,
            gate_reason="replay of frame {}".format(record.record_id),
            replay_cutoff=frame.as_of,
        ))
        outcomes.append(ResearchOutcome(
            judgment,
            trend,
            guidance,
            agent_outcome.escalated,
            agent_outcome.report,
            None,
            agent_outcome.factor_hypotheses,
            agent_outcome.summary,
        ))
    return outcomes


def snapshot_from_record(record: FrameLedgerRecord) -> MarketSnapshot:
    """Rebuild the market snapshot a recorded frame was built from."""
    return MarketSnapshot(
        as_of=record.frame.as_of,
        sources=record.sources or ["ledger"],
        assets=[record.asset_snapshot],
        source_times=record.source_times,
        payload_hashes=record.payload_hashes,
        available_time=record.available_time,
        received_time=record.received_time,
    )


def _latest_judgment(records: List[MemoryRecord], asset: str) -> Optional[ContinuousJudgment]:
    matches = [record for record in records if record.asset.upper() == asset.upper()]
    return matches[-1].judgment if matches else None


def outcome_summary(outcomes: List[ResearchOutcome]) -> str:
    lines = []
    for outcome in outcomes:
        action = "investigate" if outcome.investigated else "observe_only"
        headline = outcome.report.headline if outcome.report else outcome.judgment.selected_value
        lines.append("{} {}: {}".format(action, outcome.judgment.asset, headline))
    return "\n".join(lines)


def run_research(
    snapshot_loader: Callable[[], MarketSnapshot],
    memory: JsonlMemory,
    report_generator: Optional[ReportGenerator] = None,
    contextual_report_generator: Optional[ContextualReportGenerator] = None,
    observer: Optional[JudgmentProvider] = None,
    ledger: Optional[JsonlLedger] = None,
    reviewer: Optional[OutcomeReviewer] = None,
    factor_store: Optional[JsonlFactorStore] = None,
    asset: Optional[str] = None,
    cycles: int = 1,
    interval: float = 300.0,
    on_cycle: Optional[Callable[[List[ResearchOutcome]], None]] = None,
    agent_runner: Optional[AgentRunner] = None,
    always_investigate: bool = False,
) -> int:
    """Run the gated research loop; cycles=0 means continue until interrupted."""
    if cycles < 0 or interval < 0:
        raise ValueError("cycles and interval must be zero or greater")
    completed = 0
    while cycles == 0 or completed < cycles:
        snapshot = snapshot_loader()
        outcomes = process_snapshot(
            snapshot, memory, report_generator, asset, contextual_report_generator,
            observer, ledger, reviewer, factor_store, agent_runner, always_investigate,
        )
        if reviewer and ledger:
            reviewer.review_due(snapshot, ledger)
        if on_cycle:
            on_cycle(outcomes)
        completed += 1
        if cycles == 0 or completed < cycles:
            time.sleep(interval)
    return completed
