import json

from tellagent.gate import should_investigate
from tellagent.memory import JsonlMemory, memory_summary
from tellagent.observer import RuleBasedJevObserver, build_state_frame
from helpers import market_snapshot


def test_memory_appends_and_retrieves_related_context(tmp_path):
    snapshot = market_snapshot()
    judgment = RuleBasedJevObserver().judge(build_state_frame(snapshot, snapshot.assets[1]))
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    memory.append(judgment, "ETH 杠杆增长快于现货", tags=["leverage", "spot"])
    related = memory.related("ETH", state="leverage_led", tags=["spot"])
    assert len(related) == 1
    assert "杠杆" in memory_summary(related)
    assert json.loads((tmp_path / "memory.jsonl").read_text())['asset'] == "ETH"


def test_gate_passes_significant_judgment():
    snapshot = market_snapshot()
    judgment = RuleBasedJevObserver().judge(build_state_frame(snapshot, snapshot.assets[1]))
    assert should_investigate(judgment)
