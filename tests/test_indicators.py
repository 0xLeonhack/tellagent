from datetime import datetime, timezone

import httpx
import pytest

from tellagent.data import load_live_snapshot


def test_live_snapshot_computes_volatility_and_volume_ratio():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.exchange.coinbase.com":
            return httpx.Response(200, json=[
                [index * 3600, "1", "1", "1", str(100 + index), str(10 + index)]
                for index in range(8)
            ])
        return httpx.Response(200, json={"result": {"open_interest": 1000, "current_funding": 0.0}})

    snapshot = load_live_snapshot(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        now=datetime.fromtimestamp(8 * 3600, timezone.utc),
    )
    asset = snapshot.assets[0]
    assert asset.realized_volatility_6h is not None
    assert asset.realized_volatility_6h > 0
    assert asset.spot_volume_ratio_6h == pytest.approx(17 / 13.5)
