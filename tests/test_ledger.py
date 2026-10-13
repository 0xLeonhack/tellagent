from tellagent.ledger import JsonlLedger
from tellagent.memory import JsonlMemory
from tellagent.research import process_snapshot
from helpers import market_snapshot


def test_ledger_records_every_frame_and_judgment(tmp_path):
    snapshot = market_snapshot().model_copy(update={
        "available_time": "2026-10-08T00:00:01Z",
        "received_time": "2026-10-08T00:00:01Z",
        "source_times": {"coinbase:ETH": "2026-10-07T23:00:00Z"},
        "payload_hashes": {"coinbase:ETH": "abc"},
    })
    ledger = JsonlLedger(tmp_path)
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    process_snapshot(snapshot, memory, asset="ETH", ledger=ledger)

    frame_lines = (tmp_path / "frames" / "2026-10-08.jsonl").read_text().splitlines()
    judgment_lines = (tmp_path / "judgments" / "2026-10-08.jsonl").read_text().splitlines()
    assert len(frame_lines) == 1
    assert len(judgment_lines) == 1
    assert ledger.latest_judgment("ETH").asset == "ETH"
