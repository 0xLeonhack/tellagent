from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .schemas import ContinuousJudgment


class EventDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["silent", "open_event", "update_event"]
    event_key: str
    reason: str = Field(min_length=1)
    probability_delta: float = 0.0


def evaluate_transition(
    current: ContinuousJudgment,
    previous: Optional[ContinuousJudgment] = None,
    open_event: bool = False,
) -> EventDecision:
    """Apply deterministic event policy to adjacent judgments."""
    event_key = "{}:{}".format(current.asset, current.selected_value)
    if previous is None:
        if current.research_priority in {"significant", "urgent"}:
            return EventDecision(
                action="open_event",
                event_key=event_key,
                reason="initial judgment has elevated research priority",
            )
        return EventDecision(action="silent", event_key=event_key, reason="initial judgment is not actionable")

    previous_probability = previous.probabilities.get(current.selected_value, 0.0)
    current_probability = current.probabilities.get(current.selected_value, 0.0)
    delta = round(current_probability - previous_probability, 4)
    state_changed = current.selected_value != previous.selected_value
    meaningful_jump = delta >= 0.2
    elevated = current.research_priority in {"significant", "urgent"}
    if state_changed or meaningful_jump or elevated:
        action = "update_event" if open_event else "open_event"
        reason_parts = []
        if state_changed:
            reason_parts.append("state changed")
        if meaningful_jump:
            reason_parts.append("probability jumped by {:.2f}".format(delta))
        if elevated:
            reason_parts.append("priority is {}".format(current.research_priority))
        return EventDecision(
            action=action,
            event_key=event_key,
            reason="; ".join(reason_parts),
            probability_delta=delta,
        )
    return EventDecision(
        action="silent",
        event_key=event_key,
        reason="no state transition or meaningful probability change",
        probability_delta=delta,
    )
