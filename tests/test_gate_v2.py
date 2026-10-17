import pytest

from tellagent.gate import evaluate_gate
from tellagent.schemas import ContinuousJudgment, JudgmentTrend


def _judgment(
    state="spot_confirmed_up",
    probability=0.7,
    priority="significant",
    contradicting=None,
    insufficient=0.05,
):
    probabilities = {state: probability, "insufficient_data": insufficient}
    return ContinuousJudgment(
        frame_id="f-" + state,
        asset="BTC",
        as_of="2026-10-17T00:00:00Z",
        selected_value=state,
        probabilities=probabilities,
        confidence=probability,
        research_priority=priority,
        contradicting_roles=contradicting or [],
        provider="test",
        model_version="test",
        latency_ms=0,
        created_at="2026-10-17T00:00:00Z",
    )


def _trend(consecutive, delta_1=None):
    return JudgmentTrend(
        asset="BTC",
        state="spot_confirmed_up",
        probability_delta_1=delta_1,
        probability_ewma_12=0.7,
        consecutive_state_frames=consecutive,
        state_flips_12=1,
    )


def test_single_frame_material_state_change_opens_immediately():
    previous = _judgment("quiet", 0.7, priority="silent")
    current = _judgment("spot_confirmed_up", 0.7, priority="watch")
    decision = evaluate_gate(current, previous, event_open=False, trend=_trend(1))
    assert decision.action == "open_event"
    assert decision.triggers == ["state_changed"]


def test_confirmed_state_change_opens_exactly_one_event():
    previous = _judgment("quiet", 0.7, priority="silent")
    current = _judgment("spot_confirmed_up", 0.7, priority="watch")
    first = evaluate_gate(current, previous, event_open=False, trend=_trend(1))
    second = evaluate_gate(current, current, event_open=True, trend=_trend(2))
    third = evaluate_gate(current, current, event_open=True, trend=_trend(3))
    assert first.action == "open_event"
    assert second.action == "silent"
    assert third.action == "silent"


def test_low_probability_state_change_is_not_material():
    previous = _judgment("quiet", 0.7, priority="silent")
    current = _judgment("unconfirmed_move_up", 0.2, priority="watch")
    decision = evaluate_gate(current, previous, event_open=False, trend=_trend(2))
    assert decision.action == "silent"
    assert "not material" in decision.reason


def test_deescalation_to_quiet_is_silent():
    previous = _judgment("spot_confirmed_up", 0.7)
    current = _judgment("quiet", 0.7, priority="silent")
    decision = evaluate_gate(current, previous, event_open=True, trend=_trend(2))
    assert decision.action == "silent"


def test_insufficient_data_never_escalates():
    current = _judgment("insufficient_data", 0.9, priority="urgent", insufficient=0.9)
    decision = evaluate_gate(current, None)
    assert decision.action == "silent"
    assert decision.triggers == ["insufficient_data"]


def test_data_recovery_with_significant_evidence_is_an_event():
    previous = _judgment("insufficient_data", 0.9, priority="silent", insufficient=0.9)
    current = _judgment("leverage_expansion_down", 0.7, priority="significant")
    decision = evaluate_gate(current, previous, event_open=False, trend=_trend(1))
    assert decision.action == "open_event"
    assert decision.triggers == ["data_recovered"]


def test_data_recovery_into_material_watch_state_opens_immediately():
    previous = _judgment("insufficient_data", 0.9, priority="silent", insufficient=0.9)
    current = _judgment("unconfirmed_move_down", 0.6, priority="watch")
    decision = evaluate_gate(current, previous, event_open=False, trend=_trend(1))
    assert decision.action == "open_event"
    assert decision.triggers == ["data_recovered"]


def test_initial_material_watch_state_is_not_missed():
    current = _judgment("spot_confirmed_up", 0.6, priority="watch")
    decision = evaluate_gate(current, None, event_open=False, trend=_trend(1))
    assert decision.action == "open_event"
    assert decision.triggers == ["initial_signal"]


def test_urgent_state_change_bypasses_confirmation():
    previous = _judgment("quiet", 0.7, priority="silent")
    current = _judgment("leverage_expansion_down", 0.7, priority="urgent")
    decision = evaluate_gate(current, previous, event_open=False, trend=_trend(1))
    assert decision.action == "open_event"
    assert "state_changed" in decision.triggers


def test_probability_collapse_still_escalates():
    previous = _judgment(probability=0.5)
    current = _judgment(probability=0.2)
    decision = evaluate_gate(current, previous, event_open=False)
    assert decision.action == "open_event"
    assert decision.probability_delta == pytest.approx(-0.3)
    assert "probability_moved" in decision.triggers


def test_small_probability_move_stays_silent():
    decision = evaluate_gate(_judgment(probability=0.48), _judgment(probability=0.5), event_open=True)
    assert decision.action == "silent"
    assert decision.triggers == []


def test_material_conflict_change_updates_immediately():
    previous = _judgment(probability=0.6, contradicting=[])
    current = _judgment(probability=0.6, contradicting=["spot_confirmation"])
    unconfirmed = evaluate_gate(current, previous, event_open=True, trend=_trend(1))
    confirmed = evaluate_gate(current, previous, event_open=True, trend=_trend(2))
    assert unconfirmed.action == "update_event"
    assert "conflicts_changed" in unconfirmed.triggers
    assert "conflicts_changed" in confirmed.triggers
    weak = evaluate_gate(
        _judgment(probability=0.3, contradicting=["spot_confirmation"]),
        _judgment(probability=0.3, contradicting=[]),
        event_open=True,
        trend=_trend(2),
    )
    assert weak.action == "silent"


def test_probability_escalation_below_materiality_is_silent():
    previous = _judgment(probability=0.42, priority="watch")
    current = _judgment(probability=0.40, priority="significant")
    decision = evaluate_gate(current, previous, event_open=True, trend=_trend(2))
    assert decision.action == "silent"


def test_same_state_update_uses_update_event():
    previous = _judgment(probability=0.5)
    current = _judgment(probability=0.8)
    decision = evaluate_gate(current, previous, event_open=True, trend=_trend(3))
    assert decision.action == "update_event"
    assert "probability_moved" in decision.triggers


def test_new_state_uses_open_event_even_if_another_event_is_open():
    previous = _judgment("quiet", 0.7, priority="silent")
    current = _judgment("spot_confirmed_up", 0.7)
    decision = evaluate_gate(current, previous, event_open=True, trend=_trend(2))
    assert decision.action == "open_event"
