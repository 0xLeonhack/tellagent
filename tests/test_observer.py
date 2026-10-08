import json

import httpx
import pytest

from tellagent.observer import RemoteJevObserver, RuleBasedJevObserver, build_state_frame
from helpers import market_snapshot


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
        content = {
            "selected_value": "leverage_led",
            "probabilities": {"leverage_led": 0.8, "spot_confirmed": 0.1, "deleveraging": 0.02, "uncertain": 0.08},
            "confidence": 0.8,
            "supporting_roles": ["leverage_state"],
            "contradicting_roles": ["spot_confirmation"],
            "missing_roles": [],
            "research_priority": "significant",
            "invalidation_conditions": ["OI falls"],
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})

    snapshot = market_snapshot()
    frame = build_state_frame(snapshot, snapshot.assets[1])
    judgment = RemoteJevObserver("https://jev.test/judge", "key", "jev-test").judge(
        frame, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert judgment.provider == "jev"
    assert judgment.model_version == "jev-test"


def test_remote_jev_rejects_bad_probability_sum():
    def handler(request: httpx.Request) -> httpx.Response:
        content = {
            "selected_value": "uncertain", "probabilities": {"uncertain": 0.4},
            "confidence": 0.4, "research_priority": "watch",
            "invalidation_conditions": ["more data"],
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})

    snapshot = market_snapshot()
    frame = build_state_frame(snapshot, snapshot.assets[0])
    with pytest.raises(ValueError, match="probabilities must sum"):
        RemoteJevObserver("https://jev.test/judge", "key", "jev-test").judge(
            frame, client=httpx.Client(transport=httpx.MockTransport(handler))
        )
