from typing import Iterable, Optional

from .schemas import ContinuousJudgment, JudgmentTrend


def compute_judgment_trend(
    current: ContinuousJudgment,
    history: Iterable[ContinuousJudgment],
) -> JudgmentTrend:
    previous = [item for item in history if item.asset.upper() == current.asset.upper()][-12:]
    state = current.selected_value
    current_probability = current.probabilities.get(state, 0.0)
    sequence = previous + [current]
    consecutive = 1
    for item in reversed(previous):
        if item.selected_value != state:
            break
        consecutive += 1
    flips = sum(
        1 for left, right in zip(sequence, sequence[1:])
        if left.selected_value != right.selected_value
    )
    probabilities = [item.probabilities.get(state, 0.0) for item in sequence]
    ewma = probabilities[0]
    for value in probabilities[1:]:
        ewma = 0.3 * value + 0.7 * ewma
    return JudgmentTrend(
        asset=current.asset,
        state=state,
        probability_delta_1=_delta(current_probability, previous, 1, state),
        probability_delta_3=_delta(current_probability, previous, 3, state),
        probability_delta_12=_delta(current_probability, previous, 12, state),
        probability_ewma_12=round(ewma, 4),
        consecutive_state_frames=consecutive,
        state_flips_12=flips,
        confidence_delta_3=_confidence_delta(current, previous),
    )


def _delta(current: float, history: list[ContinuousJudgment], offset: int, state: str) -> Optional[float]:
    if len(history) < offset:
        return None
    return round(current - history[-offset].probabilities.get(state, 0.0), 4)


def _confidence_delta(current: ContinuousJudgment, history: list[ContinuousJudgment]) -> Optional[float]:
    if len(history) < 3:
        return None
    return round(current.confidence - history[-3].confidence, 4)
