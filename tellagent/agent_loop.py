from dataclasses import dataclass
from typing import Callable, Optional

from .agent_schemas import AgentDecision, AgentTrace, ToolCall, ToolResult
from .tools import ToolRegistry


DecisionProvider = Callable[[dict, Optional[ToolResult], int], AgentDecision]


@dataclass(frozen=True)
class AgentRun:
    trace: AgentTrace
    final_decision: AgentDecision


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
            if decision.action.tool_name is not None:
                if decision.action.action in {"finish", "monitor", "wait_for_confirmation"}:
                    raise ValueError("Action {} cannot invoke a tool".format(decision.action.action))
                tool_result = self.registry.execute(ToolCall(
                    call_id="{}:{}".format(trace_id, step),
                    tool_name=decision.action.tool_name,
                    arguments=decision.action.tool_args,
                ))
                decision = decision.model_copy(update={"tool_result": tool_result})
                context = {**context, "last_tool_result": tool_result.model_dump()}
            decisions.append(decision)
            if decision.finished or decision.action.action in {"finish", "monitor", "wait_for_confirmation"}:
                return AgentRun(
                    trace=AgentTrace(trace_id=trace_id, frame_id=frame_id, decisions=decisions),
                    final_decision=decision,
                )
        raise RuntimeError("Agent exceeded max_steps without finishing")
