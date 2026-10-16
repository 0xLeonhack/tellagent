from pathlib import Path

from tellagent.agent_tools import build_research_tool_registry
from tellagent.ledger import JsonlLedger
from tellagent.memory import JsonlMemory
from tellagent.observer import RuleBasedObserver, build_state_frame
from tellagent.schemas import EvidenceBundle
from tellagent.tools import ToolCall
from helpers import market_snapshot


def test_research_tool_registry_reads_scoped_context(tmp_path: Path):
    snapshot = market_snapshot()
    asset = snapshot.assets[1]
    frame = build_state_frame(snapshot, asset)
    judgment = RuleBasedObserver().judge(frame)
    ledger = JsonlLedger(tmp_path)
    ledger.append_frame(snapshot, asset, frame)
    ledger.append_judgment(judgment)
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    memory.append(judgment, "ETH leverage expansion", tags=["spot"])

    registry = build_research_tool_registry(
        tmp_path,
        frame,
        judgment,
        EvidenceBundle(supporting=["OI increases"], contradicting=[], missing=[]),
    )
    recent = registry.execute(ToolCall(call_id="1", tool_name="read_recent_judgments", arguments={"limit": 5}))
    assert recent.ok is True
    assert recent.data["count"] == 1

    related = registry.execute(ToolCall(call_id="2", tool_name="read_similar_memory", arguments={}))
    assert related.ok is True
    assert related.data["count"] == 1

    evidence = registry.execute(ToolCall(call_id="3", tool_name="read_evidence_catalog", arguments={}))
    assert evidence.ok is True
    assert evidence.data["count"] == 1


def test_research_tool_registry_reports_missing_calibration(tmp_path: Path):
    snapshot = market_snapshot()
    frame = build_state_frame(snapshot, snapshot.assets[0])
    judgment = RuleBasedObserver().judge(frame)
    registry = build_research_tool_registry(tmp_path, frame, judgment)
    result = registry.execute(ToolCall(call_id="1", tool_name="read_outcome_calibration"))
    assert result.ok is True
    assert result.data["available"] is False
