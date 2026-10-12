import json

import httpx
import pytest

from tellagent.metrics import analyze_asset
from tellagent.observer import RemoteJevObserver, RuleBasedJevObserver, build_state_frame
from tellagent.schemas import AssetSnapshot, MarketSnapshot
from helpers import market_snapshot


def test_metrics_and_observer_agree_on_state_for_same_frame():
    cases = [
        # interval OI just above threshold with spot volume in the gap that used to diverge
        AssetSnapshot(symbol="ETH", price_change_1h=0.03, spot_volume_change_1h=0.016,
                      funding_rate=0.0001, open_interest_change_interval=0.02),
        AssetSnapshot(symbol="ETH", price_change_1h=0.042, spot_volume_change_1h=0.012,
                      funding_rate=0.00024, open_interest_change_1h=0.11),
        AssetSnapshot(symbol="BTC", price_change_1h=0.028, spot_volume_change_1h=0.09,
                      funding_rate=0.00008, open_interest_change_1h=0.04),
        AssetSnapshot(symbol="BTC", price_change_1h=-0.05, spot_volume_change_1h=0.01,
                      funding_rate=0.0001, open_interest_change_1h=-0.12),
        AssetSnapshot(symbol="ETH", price_change_1h=0.001),
    ]
    for asset in cases:
        snapshot = MarketSnapshot(as_of="2026-10-08T00:00:00Z", sources=["Coinbase", "Deribit"], assets=[asset])
        expected = analyze_asset(asset).suggested_state
        observed = RuleBasedJevObserver().judge(build_state_frame(snapshot, asset)).selected_value
        assert expected == observed, asset.symbol


def test_observer_emits_structured_leverage_judgment():
    snapshot = market_snapshot()
    frame = build_state_frame(snapshot, snapshot.assets[1])
    judgment = RuleBasedJevObserver().judge(frame)
    assert judgment.provider == "rule-based-jev"
    assert judgment.selected_value == "leverage_led"
    assert sum(judgment.probabilities.values()) == 1.0
    assert judgment.research_priority in {"watch", "significant", "urgent"}


def test_observer_marks_missing_oi_as_watch():
    snapshot = market_snapshot()
    asset = snapshot.assets[0].model_copy(update={"open_interest_change_1h": None})
    frame = build_state_frame(snapshot, asset)
    judgment = RuleBasedJevObserver().judge(frame)
    assert judgment.selected_value == "uncertain"
    assert judgment.research_priority == "watch"
    assert judgment.missing_roles


def test_remote_jev_validates_probability_contract():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "state" in body
        assert body["questions"]["market_state"]["type"] == "choice"
        return httpx.Response(200, json={"answers": {
            "market_state": {
                "type": "choice", "choice": "leverage_led", "confidence": 0.8,
                "probabilities": {"leverage_led": 0.8, "spot_confirmed": 0.1, "deleveraging": 0.02, "uncertain": 0.08},
            },
            "research_priority": {"type": "choice", "choice": "significant", "confidence": 0.9, "probabilities": {}},
            "signal_conflict": {"type": "choice", "choice": "spot_confirmation", "confidence": 0.7, "probabilities": {}},
        }})

    snapshot = market_snapshot()
    frame = build_state_frame(snapshot, snapshot.assets[1])
    judgment = RemoteJevObserver("https://jev.test/judge", "key", "jev-test").judge(
        frame, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert judgment.provider == "jev"
    assert judgment.model_version == "jev-test"


def test_remote_jev_rejects_bad_probability_sum():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answers": {
            "market_state": {
                "type": "choice", "choice": "uncertain", "confidence": 0.4,
                "probabilities": {"leverage_led": 0.1, "spot_confirmed": 0.1, "deleveraging": 0.1, "uncertain": 0.1},
            },
            "research_priority": {"type": "choice", "choice": "watch", "confidence": 0.6, "probabilities": {}},
            "signal_conflict": {"type": "choice", "choice": "aligned", "confidence": 0.8, "probabilities": {}},
        }})

    snapshot = market_snapshot()
    frame = build_state_frame(snapshot, snapshot.assets[0])
    with pytest.raises(ValueError, match="probabilities must sum"):
        RemoteJevObserver("https://jev.test/judge", "key", "jev-test").judge(
            frame, client=httpx.Client(transport=httpx.MockTransport(handler))
        )
