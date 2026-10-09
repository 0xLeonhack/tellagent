from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .schemas import ContinuousJudgment


class GateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["silent", "open_event", "update_event"]
    event_key: str
    reason: str = Field(min_length=1)
    probability_delta: float = 0.0


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
    priority_rank = {"silent": 0, "watch": 1, "significant": 2, "urgent": 3}
    priority_escalated = priority_rank[current.research_priority] > priority_rank[previous.research_priority]
    conflicts_changed = set(current.contradicting_roles) != set(previous.contradicting_roles)
    if changed or jumped or priority_escalated or conflicts_changed:
        reasons = []
        if changed:
            reasons.append("state changed")
        if jumped:
            reasons.append("probability jumped by {:.2f}".format(delta))
        if priority_escalated:
            reasons.append("priority escalated to {}".format(current.research_priority))
        if conflicts_changed:
            reasons.append("contradicting roles changed")
        return GateDecision(
            action="update_event" if event_open else "open_event",
            event_key=event_key,
            reason="; ".join(reasons),
            probability_delta=delta,
        )
    return GateDecision(
        action="silent",
        event_key=event_key,
        reason="stable judgment; strong analyst cooldown applies",
        probability_delta=delta,
    )


def should_investigate(
    current: ContinuousJudgment,
    previous: Optional[ContinuousJudgment] = None,
    event_open: bool = False,
) -> bool:
    """Decide whether a stronger model should receive this judgment."""
    decision = evaluate_gate(current, previous, event_open)
    return decision.action in {"open_event", "update_event"}
