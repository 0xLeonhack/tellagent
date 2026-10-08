from dataclasses import dataclass
import time
from typing import Callable, List, Optional

from .gate import should_investigate
from .memory import JsonlMemory, memory_summary
from .observer import RuleBasedJevObserver, build_state_frame
from .schemas import AssetSnapshot, ContinuousJudgment, MarketReport, MarketSnapshot, MemoryRecord


ReportGenerator = Callable[[MarketSnapshot, AssetSnapshot], MarketReport]
ContextualReportGenerator = Callable[
    [MarketSnapshot, AssetSnapshot, ContinuousJudgment, str], MarketReport
]
Observer = RuleBasedJevObserver


@dataclass(frozen=True)
class ResearchOutcome:
    judgment: ContinuousJudgment
    investigated: bool
    report: Optional[MarketReport]
    memory_record: Optional[MemoryRecord]


def process_snapshot(
    snapshot: MarketSnapshot,
    memory: JsonlMemory,
    report_generator: Optional[ReportGenerator] = None,
    asset: Optional[str] = None,
    contextual_report_generator: Optional[ContextualReportGenerator] = None,
    observer: Optional[Observer] = None,
) -> List[ResearchOutcome]:
    """Run Observer gate, optional strong analysis, and selective memory write."""
    observer = observer or RuleBasedJevObserver()
    records = memory.records()
    selected = [item for item in snapshot.assets if not asset or item.symbol.upper() == asset.upper()]
    if not selected:
        raise ValueError("Asset not found in snapshot: {}".format(asset))
    outcomes = []
    for item in selected:
        frame = build_state_frame(snapshot, item)
        judgment = observer.judge(frame)
        previous = _latest_judgment(records, item.symbol)
        investigate = should_investigate(judgment, previous, event_open=previous is not None)
        related_context = memory_summary(
            memory.related(item.symbol, state=judgment.selected_value, tags=judgment.contradicting_roles)
        )
        if investigate and contextual_report_generator:
            report = contextual_report_generator(snapshot, item, judgment, related_context)
        elif investigate and report_generator:
            report = report_generator(snapshot, item)
        else:
            report = None
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
        outcomes.append(ResearchOutcome(judgment, investigate, report, memory_record))
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
    observer: Optional[Observer] = None,
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
        outcomes = process_snapshot(
            snapshot_loader(), memory, report_generator, asset, contextual_report_generator, observer
        )
        if on_cycle:
            on_cycle(outcomes)
        completed += 1
        if cycles == 0 or completed < cycles:
            time.sleep(interval)
    return completed
