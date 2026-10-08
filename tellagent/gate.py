from typing import Optional

from .event_policy import evaluate_transition
from .schemas import ContinuousJudgment


def should_investigate(
    current: ContinuousJudgment,
    previous: Optional[ContinuousJudgment] = None,
    event_open: bool = False,
) -> bool:
    """Decide whether a stronger model should receive this judgment."""
    decision = evaluate_transition(current, previous, event_open)
    return decision.action in {"open_event", "update_event"}
