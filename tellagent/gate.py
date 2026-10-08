from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .schemas import ContinuousJudgment


class GateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["silent", "open_event", "update_event"]
    event_key: str
    reason: str = Field(min_length=1)


def evaluate_gate(
    current: ContinuousJudgment,
    previous: Optional[ContinuousJudgment] = None,
    event_open: bool = False,
) -> GateDecision:
    """Deterministically decide whether Jev output reaches the strong model."""
    event_key = "{}:{}".format(current.asset, current.selected_value)
    if previous is None:
        if current.research_priority in {"significant", "urgent"}:
            return GateDecision(action="open_event", event_key=event_key, reason="initial judgment has elevated research priority")
        return GateDecision(action="silent", event_key=event_key, reason="initial judgment is not actionable")
    delta = round(current.probabilities.get(current.selected_value, 0.0) - previous.probabilities.get(current.selected_value, 0.0), 4)
    changed = current.selected_value != previous.selected_value
    jumped = delta >= 0.2
    elevated = current.research_priority in {"significant", "urgent"}
    if changed or jumped or elevated:
        reasons = []
        if changed:
            reasons.append("state changed")
        if jumped:
            reasons.append("probability jumped by {:.2f}".format(delta))
        if elevated:
            reasons.append("priority is {}".format(current.research_priority))
        return GateDecision(action="update_event" if event_open else "open_event", event_key=event_key, reason="; ".join(reasons))
    return GateDecision(action="silent", event_key=event_key, reason="no state transition or meaningful probability change")


def should_investigate(
    current: ContinuousJudgment,
    previous: Optional[ContinuousJudgment] = None,
    event_open: bool = False,
) -> bool:
    """Decide whether a stronger model should receive this judgment."""
    decision = evaluate_gate(current, previous, event_open)
    return decision.action in {"open_event", "update_event"}
