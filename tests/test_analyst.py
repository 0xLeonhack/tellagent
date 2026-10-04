import json

import httpx

from tellagent.analyst import RemoteAnalystConfig, generate_remote_report
from tellagent.data import load_fixture


def test_remote_analyst_validates_and_trusts_snapshot_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "headline": "模型整理的研究判断",
                        "state": "leverage_led",
                        "confidence": 0.7,
                        "supporting_evidence": ["OI 增长"],
                        "contradicting_evidence": ["现货仍有增加"],
                        "missing_evidence": ["没有链上数据"],
                        "invalidation_condition": "OI 回落且现货持续增加",
                    })
                }
            }]
        }
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json=body)

    snapshot = load_fixture()
    report = generate_remote_report(
        snapshot,
        snapshot.assets[0],
        RemoteAnalystConfig("https://model.test/chat", "test-key", "test-model"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert report.asset == "BTC"
    assert report.data_time == snapshot.as_of
    assert report.sources == snapshot.sources
    assert report.state == "leverage_led"
