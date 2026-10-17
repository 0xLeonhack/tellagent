import json
from datetime import datetime, timezone
from types import SimpleNamespace

from tellagent.audit import _compare_live, _compare_recorded_history, _spot_metrics, audit_ledger
from tellagent.ledger import JsonlLedger
from tellagent.memory import JsonlMemory
from tellagent.observer import legacy_frame_fingerprint
from tellagent.research import process_snapshot
from tellagent.schemas import AssetSnapshot, MarketSnapshot

HASH = "a" * 64


def _snapshot(as_of, price=0.03, volume=0.08, oi=0.001, **updates):
    prefix = as_of[:10]
    source_time = updates.pop("source_time", as_of)
    return MarketSnapshot(
        as_of=as_of,
        sources=["Coinbase", "Deribit"],
        assets=[AssetSnapshot(
            symbol="BTC",
            price_change_1h=price,
            spot_volume_change_1h=volume,
            spot_volume_ratio_6h=2.0,
            funding_rate=0.0001,
            open_interest_change_interval=oi,
            **updates,
        )],
        available_time=as_of,
        received_time=as_of,
        source_times={
            "coinbase:BTC": source_time,
            "deribit:BTC": source_time,
        },
        payload_hashes={"coinbase:BTC": HASH, "deribit:BTC": HASH},
    )


def _record(ledger, memory, as_of, **updates):
    return process_snapshot(_snapshot(as_of, **updates), memory, ledger=ledger)[0]


def test_clean_ledger_passes_every_check(tmp_path):
    ledger = JsonlLedger(tmp_path)
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    _record(ledger, memory, "2026-10-08T00:00:00Z", price=0.001, volume=0.0, oi=0.0)
    _record(ledger, memory, "2026-10-08T00:05:00Z")
    _record(ledger, memory, "2026-10-08T00:10:00Z")

    report = audit_ledger(tmp_path)

    assert report.ok, [check for check in report.checks if not check.ok]
    assert report.frames == 3
    assert report.judgments == 3
    assert report.reproduced == 3


def test_frame_id_tampering_is_detected(tmp_path):
    ledger = JsonlLedger(tmp_path)
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    _record(ledger, memory, "2026-10-08T00:00:00Z")
    path = tmp_path / "frames" / "2026-10-08.jsonl"
    record = json.loads(path.read_text().splitlines()[0])
    record["frame"]["as_of"] = "2026-10-08T00:00:01Z"
    # A source timestamp later than the collection time is impossible.
    record["source_times"]["coinbase:BTC"] = "2026-10-08T00:00:10Z"
    path.write_text(json.dumps(record) + "\n")

    report = audit_ledger(tmp_path)

    assert not report.ok
    failed = {check.name for check in report.checks if not check.ok}
    assert "frame_ids" in failed
    assert "frame_timestamps" in failed


def test_judgment_tampering_is_detected_by_reproduction(tmp_path):
    ledger = JsonlLedger(tmp_path)
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    _record(ledger, memory, "2026-10-08T00:00:00Z")
    path = tmp_path / "judgments" / "2026-10-08.jsonl"
    judgment = json.loads(path.read_text().splitlines()[0])
    judgment["selected_value"] = "conflicting"
    path.write_text(json.dumps(judgment) + "\n")

    report = audit_ledger(tmp_path)
    failed = {check.name for check in report.checks if not check.ok}

    assert "judgment_probabilities" in failed
    assert "judgment_reproduction" in failed


def test_orphan_judgment_is_detected(tmp_path):
    ledger = JsonlLedger(tmp_path)
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    _record(ledger, memory, "2026-10-08T00:00:00Z")
    path = tmp_path / "judgments" / "2026-10-08.jsonl"
    judgment = json.loads(path.read_text().splitlines()[0])
    judgment["frame_id"] = "deadbeefdeadbeef"
    path.write_text(json.dumps(judgment) + "\n")

    report = audit_ledger(tmp_path)
    failed = {check.name for check in report.checks if not check.ok}

    assert "judgment_linkage" in failed


def _rewrite_as_legacy(tmp_path, selected_value=None):
    """Turn the newest record into a pre-v2 frame with only its stored fields."""
    frame_path = tmp_path / "frames" / "2026-10-08.jsonl"
    record = json.loads(frame_path.read_text().splitlines()[0])
    asset_data = record["asset_snapshot"]
    for name in (
        "realized_volatility_6h",
        "spot_volume_ratio_6h",
        "open_interest_interval_seconds",
    ):
        asset_data.pop(name, None)
    asset = AssetSnapshot.model_validate(asset_data)
    legacy_id = legacy_frame_fingerprint(
        asset, record["frame"]["as_of"], fields=set(asset_data)
    )
    record["record_id"] = legacy_id
    record["frame"]["frame_id"] = legacy_id
    frame_path.write_text(json.dumps(record) + "\n")

    judgment_path = tmp_path / "judgments" / "2026-10-08.jsonl"
    judgment = json.loads(judgment_path.read_text().splitlines()[0])
    judgment["frame_id"] = legacy_id
    judgment["model_version"] = "market-state-v2"
    if selected_value is not None:
        judgment["selected_value"] = selected_value
    judgment_path.write_text(json.dumps(judgment) + "\n")
    return legacy_id


def test_legacy_frame_ids_use_the_field_set_that_was_stored(tmp_path):
    ledger = JsonlLedger(tmp_path)
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    _record(ledger, memory, "2026-10-08T00:00:00Z")
    _rewrite_as_legacy(tmp_path)

    report = audit_ledger(tmp_path)

    assert report.ok, [check for check in report.checks if not check.ok]
    legacy = {check.name: check for check in report.checks}
    assert "legacy format" in legacy["frame_ids"].detail
    assert legacy["judgment_legacy_coherence"].ok
    # Only current-version judgments are re-derived; legacy ones cannot be.
    assert report.reproduced == 0
    assert report.legacy_checked == 1


def test_legacy_judgment_must_agree_with_its_frozen_assessment(tmp_path):
    ledger = JsonlLedger(tmp_path)
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    _record(ledger, memory, "2026-10-08T00:00:00Z")
    _rewrite_as_legacy(tmp_path, selected_value="conflicting")

    report = audit_ledger(tmp_path)
    failed = {check.name for check in report.checks if not check.ok}

    assert "judgment_legacy_coherence" in failed


def test_legacy_rule_scores_may_use_the_old_non_argmax_contract(tmp_path):
    ledger = JsonlLedger(tmp_path)
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    _record(ledger, memory, "2026-10-08T00:00:00Z")
    _rewrite_as_legacy(tmp_path)
    judgment_path = tmp_path / "judgments" / "2026-10-08.jsonl"
    judgment = json.loads(judgment_path.read_text().splitlines()[0])
    selected = judgment["selected_value"]
    rival = next(name for name in judgment["probabilities"] if name != selected)
    judgment["probabilities"] = {
        name: 0.0 for name in judgment["probabilities"]
    }
    judgment["probabilities"][selected] = 0.0
    judgment["probabilities"][rival] = 1.0
    judgment_path.write_text(json.dumps(judgment) + "\n")

    report = audit_ledger(tmp_path)

    assert report.ok, [check for check in report.checks if not check.ok]
    assert report.legacy_checked == 1


def _candles(now):
    start = int(now.timestamp()) - 8 * 3600
    return [
        [start + index * 3600, 0.0, 0.0, 0.0, 100.0 + index, 10.0 + index]
        for index in range(8)
    ]


def _frame_record(asset, as_of, received_time, source_times=None):
    return SimpleNamespace(
        frame=SimpleNamespace(asset=asset.symbol, as_of=as_of),
        asset_snapshot=asset,
        received_time=received_time,
        source_times=source_times or {},
    )


def test_recorded_frame_matches_public_candle_history():
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
    candles = _candles(now)
    metrics = _spot_metrics(candles, now)
    asset = AssetSnapshot(
        symbol="BTC",
        spot_price=metrics["spot_price"],
        price_change_1h=metrics["price_change_1h"],
        price_change_6h=metrics["price_change_6h"],
        realized_volatility_6h=metrics["realized_volatility_6h"],
        spot_volume_change_1h=metrics["spot_volume_change_1h"],
        spot_volume_ratio_6h=metrics["spot_volume_ratio_6h"],
    )
    record = _frame_record(
        asset,
        "2026-10-08T12:00:00Z",
        "2026-10-08T12:10:00Z",
        {"coinbase:BTC": "2026-10-08T12:00:00Z"},
    )

    check = _compare_recorded_history("BTC", [record], candles)

    assert check.ok
    assert "1 recorded frames" in check.detail


def test_recorded_frame_tampering_is_detected_against_candle_history():
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
    candles = _candles(now)
    metrics = _spot_metrics(candles, now)
    asset = AssetSnapshot(
        symbol="BTC",
        spot_price=metrics["spot_price"] + 1.0,
        price_change_1h=metrics["price_change_1h"],
        price_change_6h=metrics["price_change_6h"],
        realized_volatility_6h=metrics["realized_volatility_6h"],
        spot_volume_change_1h=metrics["spot_volume_change_1h"],
        spot_volume_ratio_6h=metrics["spot_volume_ratio_6h"],
    )
    record = _frame_record(
        asset,
        "2026-10-08T12:00:00Z",
        "2026-10-08T12:10:00Z",
        {"coinbase:BTC": "2026-10-08T12:00:00Z"},
    )

    check = _compare_recorded_history("BTC", [record], candles)

    assert not check.ok
    assert "spot_price" in check.detail


def test_frame_captured_before_candle_settlement_is_not_compared_exactly():
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
    candles = _candles(now)
    asset = AssetSnapshot(symbol="BTC", spot_price=999999.0)
    record = _frame_record(
        asset,
        "2026-10-08T12:00:00Z",
        "2026-10-08T12:01:00Z",
        {"coinbase:BTC": "2026-10-08T12:00:00Z"},
    )

    check = _compare_recorded_history("BTC", [record], candles)

    assert check.ok
    assert "still settling" in check.detail


def test_live_comparison_accepts_live_ticker_drift():
    loaded = AssetSnapshot(
        symbol="BTC",
        spot_price=100.0,
        price_change_1h=0.01,
        price_change_6h=0.02,
        realized_volatility_6h=0.005,
        spot_volume_change_1h=0.1,
        spot_volume_ratio_6h=1.2,
        funding_rate=0.000100,
        open_interest=1000.0,
    )
    recomputed = {
        "spot_price": 100.0,
        "price_change_1h": 0.01,
        "price_change_6h": 0.02,
        "realized_volatility_6h": 0.005,
        "spot_volume_change_1h": 0.1,
        "spot_volume_ratio_6h": 1.2,
        # Funding is a live prediction; a 40% drift is normal between calls.
        "funding_rate": 0.000140,
        # OI moves by seconds of trading, so a 1% drift is normal.
        "open_interest": 1010.0,
        "index_price": 100.1,
    }
    checks = _compare_live("BTC", loaded, recomputed, {})

    assert all(check.ok for check in checks), checks


def test_live_comparison_rejects_wrong_spot_and_cross_source_drift():
    loaded = AssetSnapshot(
        symbol="BTC", spot_price=100.0, price_change_1h=0.01,
        spot_volume_change_1h=0.1,
    )
    recomputed = {
        "spot_price": 101.0,
        "price_change_1h": 0.01,
        "price_change_6h": 0.02,
        "realized_volatility_6h": 0.005,
        "spot_volume_change_1h": 0.1,
        "spot_volume_ratio_6h": 1.2,
        "funding_rate": 0.0001,
        "open_interest": 1000.0,
        "index_price": 110.0,
    }
    checks = {check.name: check for check in _compare_live("BTC", loaded, recomputed, {})}

    assert not checks["live_btc_spot"].ok
    assert not checks["live_btc_cross_source"].ok
