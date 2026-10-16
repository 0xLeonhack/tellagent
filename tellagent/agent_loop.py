from dataclasses import dataclass
from typing import Callable, Optional

from .agent_schemas import TERMINAL_ACTIONS, AgentDecision, AgentTrace, ToolCall, ToolResult
from .tools import ToolRegistry


DecisionProvider = Callable[[dict, Optional[ToolResult], int], AgentDecision]

MAX_TOOL_DATA_CHARS = 4000


@dataclass(frozen=True)
class AgentRun:
    trace: AgentTrace
    final_decision: AgentDecision
    within_budget: bool = True


class AgentLoop:
    """Finite, tool-constrained Agent loop with an explicit step budget."""

    def __init__(self, registry: ToolRegistry, max_steps: int = 3):
        if max_steps < 1 or max_steps > 10:
            raise ValueError("max_steps must be between 1 and 10")
        self.registry = registry
        self.max_steps = max_steps

    def run(
        self,
        context: dict,
        decide: DecisionProvider,
        trace_id: str,
        frame_id: str,
    ) -> AgentRun:
        decisions = []
        tool_result: Optional[ToolResult] = None
        for step in range(1, self.max_steps + 1):
            decision = decide(context, tool_result, step)
            if decision.step != step:
                raise ValueError("Agent decision step mismatch: expected {}".format(step))
            terminal_action = decision.action.action in TERMINAL_ACTIONS
            invoked_tool = decision.action.tool_name is not None
            if invoked_tool:
                if terminal_action:
                    raise ValueError("Action {} cannot invoke a tool".format(decision.action.action))
                tool_result = self.registry.execute(ToolCall(
                    call_id="{}:{}".format(trace_id, step),
                    tool_name=decision.action.tool_name,
                    arguments=decision.action.tool_args,
                ))
                decision = decision.model_copy(update={"tool_result": tool_result})
            decisions.append(decision)
            if terminal_action or decision.finished:
                return AgentRun(
                    trace=AgentTrace(trace_id=trace_id, frame_id=frame_id, decisions=decisions),
                    final_decision=decision,
                )
            if invoked_tool and step == self.max_steps:
                # The budget ran out right after a tool call. Keep the work already
                # done and close the run instead of discarding the whole decision chain.
                final = decision.model_copy(update={"finished": True})
                decisions[-1] = final
                return AgentRun(
                    trace=AgentTrace(trace_id=trace_id, frame_id=frame_id, decisions=decisions),
                    final_decision=final,
                    within_budget=False,
                )
            # The next decision sees its own earlier steps, so a model provider can
            # avoid repeating the same read and knows how much budget is left.
            context = {
                **context,
                "last_tool_result": tool_result.model_dump() if tool_result else None,
                "steps_remaining": self.max_steps - step,
                "previous_steps": [summarize_decision(item) for item in decisions],
            }
        raise RuntimeError("Agent exceeded max_steps without finishing")


def summarize_decision(decision: AgentDecision) -> dict:
    """Compact, bounded description of one decision for the next Agent step."""
    summary = {
        "step": decision.step,
        "action": decision.action.action,
        "reason": decision.action.reason,
        "tool_name": decision.action.tool_name,
        "tool_args": decision.action.tool_args,
    }
    result = decision.tool_result
    if result is not None:
        summary["tool_ok"] = result.ok
        summary["tool_error"] = result.error
        summary["tool_data"] = _bounded(result.data)
    return summary


def _bounded(data):
    text = repr(data)
    if len(text) <= MAX_TOOL_DATA_CHARS:
        return data
    return {"truncated": True, "preview": text[:MAX_TOOL_DATA_CHARS]}
