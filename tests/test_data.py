import httpx
import pytest

from tellagent.data import load_live_snapshot


def test_live_adapter_normalizes_public_responses():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.exchange.coinbase.com":
            return httpx.Response(200, json=[
                [100, "94", "96", "94", "95", "7"],
                [200, "95", "97", "95", "96", "8"],
                [300, "96", "98", "96", "97", "9"],
                [400, "97", "99", "97", "98", "10"],
                [500, "98", "100", "98", "100", "10"],
                [600, "99", "105", "100", "104", "12"],
                [700, "103", "106", "104", "105", "2"],
            ])
        return httpx.Response(200, json={"result": {"current_funding": 0.0001}})

    snapshot = load_live_snapshot(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert [asset.symbol for asset in snapshot.assets] == ["BTC", "ETH"]
    assert snapshot.assets[0].price_change_1h == 0.04
    assert snapshot.assets[0].price_change_6h == pytest.approx(104 / 95 - 1)
    assert snapshot.assets[0].spot_volume_change_1h == 0.2
    assert snapshot.assets[0].funding_rate == 0.0001
    assert snapshot.assets[0].open_interest_change_1h is None


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
