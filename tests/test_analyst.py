import json

import httpx
import pytest

from tellagent.analyst import RemoteAnalystConfig, generate_remote_report
from tellagent.evidence import build_evidence_catalog
from tellagent.metrics import analyze_asset
from tellagent.observer import RuleBasedJevObserver, build_state_frame
from helpers import market_snapshot


def test_remote_analyst_validates_and_trusts_snapshot_metadata():
    snapshot = market_snapshot()
    asset = snapshot.assets[0]
    evidence = analyze_asset(asset).evidence
    catalog = build_evidence_catalog(asset.symbol, evidence)
    ids = {
        role: [item.evidence_id for item in catalog if item.role == role]
        for role in ("supporting", "contradicting", "missing")
    }

    def handler(request: httpx.Request) -> httpx.Response:
        request_body = json.loads(request.content)
        user_facts = json.loads(request_body["messages"][1]["content"])
        assert user_facts["related_memory"] == "prior context"
        assert user_facts["jev_judgment"]["selected_value"] == "leverage_led"
        body = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "headline": "模型整理的研究判断",
                        "state": "leverage_led",
                        "confidence": 0.7,
                        "supporting_evidence_ids": ids["supporting"],
                        "contradicting_evidence_ids": ids["contradicting"],
                        "missing_evidence_ids": ids["missing"],
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
        memory_context="prior context",
        judgment=RuleBasedJevObserver().judge(build_state_frame(snapshot, asset)),
    )
    assert report.asset == "BTC"
    assert report.data_time == snapshot.as_of
    assert report.sources == snapshot.sources
    assert report.state == "leverage_led"
    assert report.supporting_evidence == evidence.supporting
    assert report.supporting_evidence_ids == ids["supporting"]


def test_remote_analyst_rejects_invented_evidence():
    def handler(request: httpx.Request) -> httpx.Response:
        content = {
            "headline": "未经输入支持的判断",
            "state": "leverage_led",
            "confidence": 0.7,
            "supporting_evidence_ids": ["BTC:supporting:invented"],
            "contradicting_evidence_ids": ["BTC:contradicting:invented"],
            "missing_evidence_ids": [],
            "invalidation_condition": "OI 回落",
        }
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(content)}}]
        })

    snapshot = market_snapshot()
    with pytest.raises(ValueError, match="unknown supporting evidence id"):
        generate_remote_report(
            snapshot,
            snapshot.assets[0],
            RemoteAnalystConfig("https://model.test/chat", "test-key", "test-model"),
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
