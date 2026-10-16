import json

from tellagent.gate import should_investigate
from tellagent.memory import JsonlMemory, memory_summary
from tellagent.observer import RuleBasedJevObserver, build_state_frame
from tellagent.schemas import ContinuousJudgment
from helpers import market_snapshot


def test_memory_appends_and_retrieves_related_context(tmp_path):
    snapshot = market_snapshot()
    judgment = RuleBasedJevObserver().judge(build_state_frame(snapshot, snapshot.assets[1]))
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    memory.append(judgment, "ETH 杠杆增长快于现货", tags=["leverage", "spot"])
    related = memory.related("ETH", state="leverage_expansion_up", tags=["spot"])
    assert len(related) == 1
    assert "杠杆" in memory_summary(related)
    assert json.loads((tmp_path / "memory.jsonl").read_text())['asset'] == "ETH"


def test_gate_passes_significant_judgment():
    snapshot = market_snapshot()
    judgment = RuleBasedJevObserver().judge(build_state_frame(snapshot, snapshot.assets[1]))
    assert should_investigate(judgment)


def test_gate_suppresses_unchanged_significant_judgment():
    snapshot = market_snapshot()
    judgment = RuleBasedJevObserver().judge(build_state_frame(snapshot, snapshot.assets[1]))
    assert should_investigate(judgment, judgment, event_open=True) is False


def test_gate_suppresses_non_actionable_data_warmup_transition():
    previous = ContinuousJudgment(
        frame_id="a", asset="BTC", as_of="t", selected_value="insufficient_data",
        probabilities={"insufficient_data": 0.65}, confidence=0.65,
        research_priority="silent", provider="test", model_version="test",
        latency_ms=0, created_at="t",
    )
    current = previous.model_copy(update={
        "frame_id": "b", "selected_value": "unconfirmed_move_down",
        "probabilities": {"unconfirmed_move_down": 0.6},
        "confidence": 0.6, "research_priority": "watch",
    })
    assert should_investigate(current, previous, event_open=True) is False
