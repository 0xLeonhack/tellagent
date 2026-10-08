import httpx
import pytest

from tellagent.data import RollingLiveLoader, load_live_snapshot
from tellagent.schemas import AssetSnapshot, MarketSnapshot


def test_live_adapter_normalizes_public_responses():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.exchange.coinbase.com":
            return httpx.Response(200, json=[
                [0, "93", "95", "93", "94", "6"],
                [100, "94", "96", "94", "95", "7"],
                [200, "95", "97", "95", "96", "8"],
                [300, "96", "98", "96", "97", "9"],
                [400, "97", "99", "97", "98", "10"],
                [500, "98", "100", "98", "100", "10"],
                [600, "99", "105", "100", "104", "12"],
                [700, "103", "106", "104", "105", "2"],
            ])
        return httpx.Response(200, json={"result": {"current_funding": 0.0001, "open_interest": 1000}})

    snapshot = load_live_snapshot(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert [asset.symbol for asset in snapshot.assets] == ["BTC", "ETH"]
    assert snapshot.assets[0].price_change_1h == 0.04
    assert snapshot.assets[0].price_change_6h == pytest.approx(104 / 94 - 1)
    assert snapshot.assets[0].spot_volume_change_1h == 0.2
    assert snapshot.assets[0].funding_rate == 0.0001
    assert snapshot.assets[0].open_interest == 1000
    assert snapshot.assets[0].open_interest_change_1h is None


def test_live_adapter_rejects_short_candle_history():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[[100, "1", "1", "1", "1", "1"]])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        load_live_snapshot(client=client)
    except ValueError as exc:
        assert "eight hourly candles" in str(exc)
    else:
        raise AssertionError("Short candle history should fail")


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
