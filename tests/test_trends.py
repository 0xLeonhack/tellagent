from tellagent.schemas import ContinuousJudgment
from tellagent.trends import compute_judgment_trend


def _judgment(frame_id, state, probability, confidence=0.7):
    probabilities = {"leverage_led": 0.1, "spot_confirmed": 0.1, "deleveraging": 0.1, "uncertain": 0.7}
    probabilities[state] = probability
    return ContinuousJudgment(
        frame_id=frame_id, asset="ETH", as_of="t", selected_value=state,
        probabilities=probabilities, confidence=confidence, research_priority="watch",
        provider="test", model_version="test", latency_ms=0, created_at="t",
    )


def test_judgment_trend_tracks_persistence_and_deltas():
    history = [_judgment(str(i), "uncertain", 0.7) for i in range(3)]
    current = _judgment("current", "leverage_led", 0.82, confidence=0.82)
    trend = compute_judgment_trend(current, history)
    assert trend.probability_delta_1 == 0.72
    assert trend.probability_delta_3 == 0.72
    assert trend.consecutive_state_frames == 1
    assert trend.state_flips_12 == 1
    assert trend.confidence_delta_3 == 0.12
