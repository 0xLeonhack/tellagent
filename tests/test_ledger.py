from tellagent.ledger import JsonlLedger
from tellagent.memory import JsonlMemory
from tellagent.research import process_snapshot
from tellagent.schemas import AssetSnapshot, MarketSnapshot
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


def test_gate_uses_adjacent_non_memory_judgment(tmp_path):
    ledger = JsonlLedger(tmp_path)
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    first = MarketSnapshot(
        as_of="2026-10-08T00:00:00Z", sources=["test"],
        assets=[AssetSnapshot(
            symbol="BTC", price_change_1h=0.001, price_change_6h=0.001,
            spot_volume_change_1h=0.0, funding_rate=0.0,
            open_interest_change_interval=0.0,
        )],
    )
    second = MarketSnapshot(
        as_of="2026-10-08T00:05:00Z", sources=["test"],
        assets=[AssetSnapshot(
            symbol="BTC", price_change_1h=0.03, spot_volume_change_1h=0.08,
            spot_volume_ratio_6h=2.0,
            funding_rate=0.0001, open_interest_change_interval=0.001,
        )],
    )
    third = second.model_copy(update={"as_of": "2026-10-08T00:10:00Z"})
    first_outcome = process_snapshot(first, memory, ledger=ledger)[0]
    assert first_outcome.investigated is False
    assert memory.records() == []
    second_outcome = process_snapshot(second, memory, ledger=ledger)[0]
    assert second_outcome.judgment.selected_value == "spot_confirmed_up"
    # One frame is not a confirmed state change: the Gate holds it.
    assert second_outcome.investigated is False
    third_outcome = process_snapshot(third, memory, ledger=ledger)[0]
    assert third_outcome.investigated is True


def test_gate_decisions_are_persisted_for_silent_and_open_frames(tmp_path):
    ledger = JsonlLedger(tmp_path)
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    first = MarketSnapshot(
        as_of="2026-10-08T00:00:00Z", sources=["test"],
        assets=[AssetSnapshot(
            symbol="BTC", price_change_1h=0.001, price_change_6h=0.001,
            spot_volume_change_1h=0.0, funding_rate=0.0,
            open_interest_change_interval=0.0,
        )],
    )
    second = MarketSnapshot(
        as_of="2026-10-08T00:05:00Z", sources=["test"],
        assets=[AssetSnapshot(
            symbol="BTC", price_change_1h=0.03, spot_volume_change_1h=0.08,
            spot_volume_ratio_6h=2.0,
            funding_rate=0.0001, open_interest_change_interval=0.001,
        )],
    )
    process_snapshot(first, memory, ledger=ledger)
    process_snapshot(second, memory, ledger=ledger)
    process_snapshot(second.model_copy(update={"as_of": "2026-10-08T00:10:00Z"}), memory, ledger=ledger)

    records = ledger.gate_decisions("BTC")
    assert [record["action"] for record in records] == ["silent", "silent", "open_event"]
    assert records[0]["investigated"] is False
    assert records[0]["bypassed"] is False
    assert records[1]["triggers"] == ["awaiting_confirmation"]
    assert records[2]["investigated"] is True
    assert "state_confirmed" in records[2]["triggers"]
