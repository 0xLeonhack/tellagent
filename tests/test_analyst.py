import json

import httpx
import pytest

from tellagent.analyst import RemoteAnalystConfig, generate_remote_report
from tellagent.data import load_fixture
from tellagent.metrics import analyze_asset


def test_remote_analyst_validates_and_trusts_snapshot_metadata():
    snapshot = load_fixture()
    asset = snapshot.assets[0]
    evidence = analyze_asset(asset).evidence

    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "headline": "模型整理的研究判断",
                        "state": "leverage_led",
                        "confidence": 0.7,
                        "supporting_evidence": evidence.supporting,
                        "contradicting_evidence": evidence.contradicting,
                        "missing_evidence": evidence.missing,
                        "invalidation_condition": "OI 回落且现货持续增加",
                    })
                }
            }]
        }
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json=body)

    report = generate_remote_report(
        snapshot,
        asset,
        RemoteAnalystConfig("https://model.test/chat", "test-key", "test-model"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert report.asset == "BTC"
    assert report.data_time == snapshot.as_of
    assert report.sources == snapshot.sources
    assert report.state == "leverage_led"


def test_remote_analyst_rejects_invented_evidence():
    def handler(request: httpx.Request) -> httpx.Response:
        content = {
            "headline": "未经输入支持的判断",
            "state": "leverage_led",
            "confidence": 0.7,
            "supporting_evidence": ["某新闻推动价格上涨"],
            "contradicting_evidence": ["现货成交量也增加了 3.10%"],
            "missing_evidence": ["未接入链上数据，链上确认仍然缺失"],
            "invalidation_condition": "OI 回落",
        }
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(content)}}]
        })

    snapshot = load_fixture()
    with pytest.raises(ValueError, match="invented supporting evidence"):
        generate_remote_report(
            snapshot,
            snapshot.assets[0],
            RemoteAnalystConfig("https://model.test/chat", "test-key", "test-model"),
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
