import pytest

from tellagent.evaluation import HistoryRow, evaluate_ledger, summarize_history
from tellagent.ledger import JsonlLedger
from tellagent.memory import JsonlMemory
from tellagent.research import process_snapshot
from tellagent.schemas import AssetSnapshot, MarketSnapshot
from tellagent.scoring import DEFAULT_PRICE_THRESHOLD, DEFAULT_VOLUME_THRESHOLD


def _history(values):
    rows = []
    for index, (close, volume) in enumerate(values):
        rows.append(HistoryRow(
            timestamp=1_700_000_000 + index * 3600,
            close=close,
            volume=volume,
            funding_8h=0.0002 if index % 10 == 0 else 0.00001,
            funding_1h=None,
        ))
    return rows


def test_summary_uses_sorted_percentiles_and_current_defaults():
    rows = _history([
        (100, 100),
        (101, 150),
        (100.5, 90),
        (102, 200),
        (99, 70),
        (103, 180),
        (104, 160),
        (106, 240),
    ])
    report = summarize_history("BTC", rows)

    assert report["hours"] == 8
    assert report["price_abs"]["count"] == 7
    assert report["price_abs"]["p50"] <= report["price_abs"]["p90"]
    # Suggestions are sorted before the percentile, and they are derived from
    # the same p90 the table displays.
    assert report["suggested"]["price_change_1h"] == pytest.approx(
        report["price_abs"]["p90"], abs=1e-12
    ) or report["suggested"]["price_change_1h"] in {0.005, 0.05}
    assert report["suggested"]["spot_volume_change_1h"] == pytest.approx(
        max(0.02, min(2.0, report["volume_abs"]["p90"])), abs=1e-12
    )
    assert report["current"]["price_change_1h"] == DEFAULT_PRICE_THRESHOLD
    assert report["current"]["spot_volume_change_1h"] == DEFAULT_VOLUME_THRESHOLD
    assert report["current"]["funding_extreme"] == pytest.approx(0.00012)


def test_forward_information_separates_large_and_quiet_moves():
    closes = [100.0]
    for _ in range(20):
        closes.append(closes[-1] * 1.01)
    rows = [
        HistoryRow(timestamp=i, close=close, volume=100.0 + i, funding_8h=0.0, funding_1h=None)
        for i, close in enumerate(closes)
    ]
    report = summarize_history("BTC", rows, price_threshold=0.005)

    assert report["large_move_share"] == pytest.approx(1.0)
    assert report["forward_abs_3h_after_large"] is not None
    assert report["continuation_after_large"] == pytest.approx(1.0)


def _snapshot(as_of, price, volume, oi):
    return MarketSnapshot(
        as_of=as_of,
        sources=["test"],
        assets=[AssetSnapshot(
            symbol="BTC",
            price_change_1h=price,
            spot_volume_change_1h=volume,
            spot_volume_ratio_6h=2.0 if volume >= 0.05 else None,
            funding_rate=0.0001,
            open_interest_change_interval=oi,
        )],
    )


def test_live_evaluation_counts_gate_v1_and_v2_escalations(tmp_path):
    ledger = JsonlLedger(tmp_path)
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    process_snapshot(_snapshot("2026-10-08T00:00:00Z", 0.001, 0.0, 0.0), memory, ledger=ledger)
    process_snapshot(_snapshot("2026-10-08T00:05:00Z", 0.03, 0.08, 0.001), memory, ledger=ledger)
    process_snapshot(_snapshot("2026-10-08T00:10:00Z", 0.03, 0.08, 0.001), memory, ledger=ledger)

    report = evaluate_ledger(tmp_path)

    assert report["judgments"] == 3
    assert report["gate_v1_escalations"] == 1
    assert report["gate_v2_escalations"] == 1
    # The old Gate fires on the first changed frame; the new Gate holds it for
    # one frame and then confirms, so it suppresses exactly that frame.
    assert report["gate_v1_suppressed_by_v2"] == 1
    assert report["suppressed_that_did_not_persist"] == 0


def test_live_evaluation_is_empty_without_a_ledger(tmp_path):
    report = evaluate_ledger(tmp_path / "missing")

    assert report["judgments"] == 0
    assert report["mean_top_probability"] is None
    assert report["gate_v1_escalations"] == 0
    assert report["gate_v2_escalations"] == 0
