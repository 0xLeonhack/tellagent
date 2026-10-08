from dataclasses import dataclass
from typing import Callable, List, Optional

from .analyst import generate_demo_report
from .gate import should_investigate
from .memory import JsonlMemory, memory_summary
from .observer import RuleBasedJevObserver, build_state_frame
from .schemas import AssetSnapshot, ContinuousJudgment, MarketReport, MarketSnapshot, MemoryRecord


ReportGenerator = Callable[[MarketSnapshot, AssetSnapshot], MarketReport]


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
) -> List[ResearchOutcome]:
    """Run Observer gate, optional strong analysis, and selective memory write."""
    observer = RuleBasedJevObserver()
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
        report = report_generator(snapshot, item) if investigate and report_generator else None
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
