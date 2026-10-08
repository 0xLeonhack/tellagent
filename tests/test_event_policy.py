from tellagent.data import load_fixture
from tellagent.event_policy import evaluate_transition
from tellagent.observer import RuleBasedJevObserver, build_state_frame
from tellagent.schemas import ContinuousJudgment


def test_significant_initial_judgment_opens_event():
    snapshot = load_fixture()
    judgment = RuleBasedJevObserver().judge(build_state_frame(snapshot, snapshot.assets[1]))
    decision = evaluate_transition(judgment)
    assert decision.action == "open_event"
    assert decision.event_key == "ETH:leverage_led"


def test_stable_judgment_is_silent():
    base = ContinuousJudgment(
        frame_id="a", asset="BTC", as_of="t", selected_value="uncertain",
        probabilities={"uncertain": 0.62, "spot_confirmed": 0.18}, confidence=0.62,
        research_priority="silent", provider="test", model_version="test", latency_ms=0,
        created_at="t",
    )
    current = base.model_copy(update={"frame_id": "b"})
    assert evaluate_transition(current, base).action == "silent"


def test_state_change_updates_existing_event():
    previous = ContinuousJudgment(
        frame_id="a", asset="ETH", as_of="t", selected_value="uncertain",
        probabilities={"uncertain": 0.62, "leverage_led": 0.12}, confidence=0.62,
        research_priority="watch", provider="test", model_version="test", latency_ms=0,
        created_at="t",
    )
    current = previous.model_copy(update={
        "frame_id": "b", "selected_value": "leverage_led",
        "probabilities": {"uncertain": 0.08, "leverage_led": 0.82},
        "confidence": 0.82, "research_priority": "significant",
    })
    decision = evaluate_transition(current, previous, open_event=True)
    assert decision.action == "update_event"
    assert decision.probability_delta == 0.7
