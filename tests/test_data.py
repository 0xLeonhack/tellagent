import httpx

from tellagent.data import load_live_snapshot


def test_live_adapter_normalizes_public_responses():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.exchange.coinbase.com":
            return httpx.Response(200, json=[
                [200, "99", "101", "100", "102", "10"],
                [400, "101", "103", "102", "104", "12"],
            ])
        return httpx.Response(200, json={"result": {"current_funding": 0.0001}})

    snapshot = load_live_snapshot(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert [asset.symbol for asset in snapshot.assets] == ["BTC", "ETH"]
    assert snapshot.assets[0].price_change_1h == 0.04
    assert snapshot.assets[0].spot_volume_change_1h == 0.2
    assert snapshot.assets[0].funding_rate == 0.0001
    assert snapshot.assets[0].open_interest_change_1h is None
