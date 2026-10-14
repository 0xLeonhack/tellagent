from datetime import datetime, timezone

import httpx
import pytest

from tellagent.data import RollingLiveLoader, load_live_snapshot
from tellagent.schemas import AssetSnapshot, MarketSnapshot


def test_live_adapter_normalizes_public_responses():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.exchange.coinbase.com":
            return httpx.Response(200, json=[
                [0, "93", "95", "93", "94", "6"],
                [3600, "94", "96", "94", "95", "7"],
                [7200, "95", "97", "95", "96", "8"],
                [10800, "96", "98", "96", "97", "9"],
                [14400, "97", "99", "97", "98", "10"],
                [18000, "98", "100", "98", "100", "10"],
                [21600, "99", "105", "100", "104", "12"],
                [25200, "103", "106", "104", "105", "2"],
            ])
        return httpx.Response(200, json={"result": {
            "current_funding": 0.0001, "open_interest": 1000, "timestamp": 1000,
        }})

    snapshot = load_live_snapshot(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=datetime.fromtimestamp(27000, timezone.utc),
    )
    assert [asset.symbol for asset in snapshot.assets] == ["BTC", "ETH"]
    assert snapshot.assets[0].price_change_1h == 0.04
    assert snapshot.assets[0].price_change_6h == pytest.approx(104 / 94 - 1)
    assert snapshot.assets[0].spot_volume_change_1h == 0.2
    assert snapshot.assets[0].funding_rate == 0.0001
    assert snapshot.assets[0].open_interest == 1000
    assert snapshot.assets[0].open_interest_change_1h is None
    assert snapshot.source_times["coinbase:BTC"] == "1970-01-01T07:00:00Z"
    assert snapshot.source_times["deribit:BTC"] == "1970-01-01T00:00:01Z"
    assert len(snapshot.payload_hashes["coinbase:BTC"]) == 64
    assert snapshot.available_time


def test_live_adapter_rejects_short_candle_history():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[[100, "1", "1", "1", "1", "1"]])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        load_live_snapshot(client=client)
    except ValueError as exc:
        assert "seven hourly candles" in str(exc)
    else:
        raise AssertionError("Short candle history should fail")


def test_live_adapter_keeps_latest_completed_candle_when_current_bucket_is_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.exchange.coinbase.com":
            return httpx.Response(200, json=[
                [index * 3600, "1", "1", "1", str(100 + index), "10"]
                for index in range(7)
            ])
        return httpx.Response(200, json={"result": {"open_interest": 1000, "timestamp": 27000000}})

    snapshot = load_live_snapshot(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=datetime.fromtimestamp(27000, timezone.utc),
    )
    assert snapshot.assets[0].spot_price == 106
    assert snapshot.source_times["coinbase:BTC"] == "1970-01-01T07:00:00Z"


def test_live_adapter_rejects_non_contiguous_hourly_candles():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.exchange.coinbase.com":
            timestamps = [0, 3600, 7200, 10800, 18000, 21600, 25200]
            return httpx.Response(200, json=[
                [timestamp, "1", "1", "1", "1", "10"] for timestamp in timestamps
            ])
        return httpx.Response(200, json={"result": {"open_interest": 1000}})

    with pytest.raises(ValueError, match="non-contiguous"):
        load_live_snapshot(
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            now=datetime.fromtimestamp(30000, timezone.utc),
        )


def test_rolling_loader_calculates_real_interval_oi_change(monkeypatch):
    values = iter([1000.0, 1020.0])

    def snapshot(timeout):
        oi = next(values)
        return MarketSnapshot(
            as_of="2026-10-08T00:00:00Z",
            sources=["Deribit"],
            assets=[AssetSnapshot(symbol="BTC", open_interest=oi)],
        )

    monkeypatch.setattr("tellagent.data.load_live_snapshot", snapshot)
    loader = RollingLiveLoader()
    assert loader().assets[0].open_interest_change_interval is None
    assert loader().assets[0].open_interest_change_interval == pytest.approx(0.02)
