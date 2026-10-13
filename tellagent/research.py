from dataclasses import dataclass
import time
from typing import Callable, List, Optional

from .gate import should_investigate
from .calibration import build_strategy_thresholds, compute_feature_baselines
from .factors import JsonlFactorStore, build_factor_hypotheses
from .ledger import JsonlLedger
from .memory import JsonlMemory, memory_summary
from .observer import JudgmentProvider, RuleBasedJevObserver, build_state_frame
from .review import OutcomeReviewer
from .schemas import (
    AssetSnapshot,
    ContinuousJudgment,
    JudgmentTrend,
    FactorHypothesis,
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
@dataclass(frozen=True)
class ResearchOutcome:
    judgment: ContinuousJudgment
    trend: JudgmentTrend
    guidance: ResearchGuidance
    investigated: bool
    report: Optional[MarketReport]
    memory_record: Optional[MemoryRecord]
    factor_hypotheses: List[FactorHypothesis]


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
) -> List[ResearchOutcome]:
    """Run Observer gate, optional strong analysis, and selective memory write."""
    observer = observer or RuleBasedJevObserver()
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
        investigate = should_investigate(
            judgment, previous, event_open=previous is not None, trend=trend
        )
        report = None
        if investigate:
            related_context = memory_summary(
                memory.related(item.symbol, state=judgment.selected_value, tags=judgment.contradicting_roles)
            )
            if contextual_report_generator:
                report = contextual_report_generator(snapshot, item, judgment, related_context)
            elif report_generator:
                report = report_generator(snapshot, item)
        summary = report.headline if report else "{}: {}".format(judgment.selected_value, judgment.research_priority)
        memory_record = None
        factor_hypotheses = []
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
            factor_hypotheses = build_factor_hypotheses(judgment, guidance, report)
            if factor_store:
                for hypothesis in factor_hypotheses:
                    factor_store.append_hypothesis(hypothesis)
        outcomes.append(ResearchOutcome(
            judgment, trend, guidance, investigate, report, memory_record, factor_hypotheses
        ))
    return outcomes


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
) -> int:
    """Run the gated research loop; cycles=0 means continue until interrupted."""
    if cycles < 0 or interval < 0:
        raise ValueError("cycles and interval must be zero or greater")
    completed = 0
    while cycles == 0 or completed < cycles:
        snapshot = snapshot_loader()
        outcomes = process_snapshot(
            snapshot, memory, report_generator, asset, contextual_report_generator,
            observer, ledger, reviewer, factor_store,
        )
        if reviewer and ledger:
            reviewer.review_due(snapshot, ledger)
        if on_cycle:
            on_cycle(outcomes)
        completed += 1
        if cycles == 0 or completed < cycles:
            time.sleep(interval)
    return completed
