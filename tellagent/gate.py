from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .schemas import ContinuousJudgment, JudgmentTrend


# The Gate protects the expensive analyst/model call without hiding a new
# market signal. A material actionable state is handed to the Agent once when
# it first appears; only stable repetitions are cooled down.
CONFIRMATION_FRAMES = 2
MATERIAL_STATE_PROBABILITY = 0.40
MATERIAL_ESCALATION_PROBABILITY = 0.50
JUMP_THRESHOLD = 0.20
TREND_JUMP_THRESHOLD = 0.25
INSUFFICIENT_MASS = 0.50

ACTIONABLE_STATES = {
    "spot_confirmed_up",
    "spot_confirmed_down",
    "leverage_expansion_up",
    "leverage_expansion_down",
    "position_unwind_up",
    "position_unwind_down",
    "broad_participation_up",
    "broad_participation_down",
    "unconfirmed_move_up",
    "unconfirmed_move_down",
    "conflicting",
}
PRIORITY_RANK = {"silent": 0, "watch": 1, "significant": 2, "urgent": 3}


class GateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["silent", "open_event", "update_event"]
    event_key: str
    reason: str = Field(min_length=1)
    probability_delta: float = 0.0
    triggers: List[str] = Field(default_factory=list)


def evaluate_gate(
    current: ContinuousJudgment,
    previous: Optional[ContinuousJudgment] = None,
    event_open: bool = False,
    trend: Optional[JudgmentTrend] = None,
) -> GateDecision:
    """Deterministically decide whether an Observer judgment reaches the analyst.

    Four safeguards keep the Gate from turning every frame into an event:

    1. **Data quality** — a judgment dominated by ``insufficient_data`` never
       escalates; there is nothing trustworthy to analyse.
    2. **Recall first** — a new actionable state is emitted immediately once;
       the Agent can then decide to monitor instead of calling the Analyst.
    3. **Materiality** — the new state must carry enough evidence weight.
    4. **Deduplication** — unchanged evidence is silent; only a material score,
       priority, or contradiction change updates an existing event.
    """
    event_key = "{}:{}".format(current.asset, current.selected_value)
    current_probability = current.probabilities.get(current.selected_value, 0.0)
    insufficient_mass = current.probabilities.get("insufficient_data", 0.0)

    if insufficient_mass >= INSUFFICIENT_MASS:
        return _silent(
            event_key,
            "insufficient data: price or open interest evidence is missing",
            triggers=["insufficient_data"],
        )

    actionable = current.selected_value in ACTIONABLE_STATES
    if previous is None:
        if (
            actionable
            and current.research_priority != "silent"
            and current_probability >= MATERIAL_STATE_PROBABILITY
        ):
            return GateDecision(
                action="open_event",
                event_key=event_key,
                reason="initial actionable signal has material evidence",
                probability_delta=round(current_probability, 4),
                triggers=["initial_signal"],
            )
        return _silent(event_key, "initial judgment is not actionable")

    previous_insufficient = previous.probabilities.get("insufficient_data", 0.0)
    if previous_insufficient >= INSUFFICIENT_MASS:
        if (
            not actionable
            or current.research_priority == "silent"
            or current_probability < MATERIAL_STATE_PROBABILITY
        ):
            return _silent(
                event_key,
                "data warmup completed without an actionable state",
                triggers=["data_warmup"],
            )
        return GateDecision(
            action="open_event",
            event_key=event_key,
            reason="data recovered into material state {}".format(current.selected_value),
            probability_delta=round(current_probability, 4),
            triggers=["data_recovered"],
        )

    delta = round(
        current_probability
        - previous.probabilities.get(current.selected_value, 0.0),
        4,
    )
    changed = current.selected_value != previous.selected_value
    confirmed = trend is None or trend.consecutive_state_frames >= CONFIRMATION_FRAMES
    triggers: List[str] = []
    reasons: List[str] = []

    if changed:
        if not actionable or current_probability < MATERIAL_STATE_PROBABILITY:
            return _silent(
                event_key,
                "state changed to {} but the evidence is not material".format(
                    current.selected_value
                ),
                delta,
            )
        triggers.append("state_changed")
        reasons.append("state changed to {}".format(current.selected_value))

    # A held state is emitted exactly once, when it reaches the confirmation
    # count. Later frames have a higher count and stay silent, so the Gate needs
    # no extra mutable event state to avoid duplicate escalation.
    just_confirmed = (
        not changed
        and not event_open
        and trend is not None
        and trend.consecutive_state_frames == CONFIRMATION_FRAMES
        and actionable
        and current_probability >= MATERIAL_STATE_PROBABILITY
        and PRIORITY_RANK[current.research_priority] >= PRIORITY_RANK["watch"]
    )
    if just_confirmed:
        triggers.append("state_confirmed")
        reasons.append(
            "state {} held for {} frames".format(
                current.selected_value, CONFIRMATION_FRAMES
            )
        )

    trend_deltas = [] if trend is None else [
        value for value in (
            trend.probability_delta_1,
            trend.probability_delta_3,
            trend.probability_delta_12,
        ) if value is not None
    ]
    largest_move = max([delta] + trend_deltas, key=abs)
    immediate_jump = abs(delta) >= JUMP_THRESHOLD
    sustained_jump = (
        any(abs(value) >= TREND_JUMP_THRESHOLD for value in trend_deltas)
        and current_probability >= MATERIAL_ESCALATION_PROBABILITY
    )
    if not changed and actionable and (immediate_jump or sustained_jump):
        triggers.append("probability_moved")
        reasons.append("selected-state probability moved by {:+.2f}".format(largest_move))

    priority_escalated = (
        PRIORITY_RANK[current.research_priority] > PRIORITY_RANK[previous.research_priority]
        and PRIORITY_RANK[current.research_priority] >= PRIORITY_RANK["significant"]
        and current_probability >= MATERIAL_ESCALATION_PROBABILITY
    )
    if priority_escalated:
        triggers.append("priority_escalated")
        reasons.append("priority escalated to {}".format(current.research_priority))

    conflicts_changed = set(current.contradicting_roles) != set(previous.contradicting_roles)
    if (
        conflicts_changed
        and current.research_priority != "silent"
        and current_probability >= MATERIAL_ESCALATION_PROBABILITY
    ):
        triggers.append("conflicts_changed")
        reasons.append("contradicting roles changed")

    if not triggers:
        return _silent(
            event_key,
            "stable judgment; strong analyst cooldown applies",
            largest_move,
        )

    same_state = current.selected_value == previous.selected_value
    return GateDecision(
        action="update_event" if event_open and same_state else "open_event",
        event_key=event_key,
        reason="; ".join(reasons),
        probability_delta=largest_move,
        triggers=triggers,
    )


def should_investigate(
    current: ContinuousJudgment,
    previous: Optional[ContinuousJudgment] = None,
    event_open: bool = False,
    trend: Optional[JudgmentTrend] = None,
) -> bool:
    """Decide whether a stronger model should receive this judgment."""
    decision = evaluate_gate(current, previous, event_open, trend)
    return decision.action in {"open_event", "update_event"}


def _silent(
    event_key: str,
    reason: str,
    probability_delta: float = 0.0,
    triggers: Optional[List[str]] = None,
) -> GateDecision:
    return GateDecision(
        action="silent",
        event_key=event_key,
        reason=reason,
        probability_delta=probability_delta,
        triggers=triggers or [],
    )
