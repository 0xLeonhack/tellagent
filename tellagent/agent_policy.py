from typing import Any, Optional

from .agent_schemas import AgentAction, AgentDecision, ToolResult


# Read sequence used when the run has spare steps: each tool decides the next one.
NEXT_READ = {
    "create_factor_hypothesis": "read_outcome_calibration",
    "read_outcome_calibration": "read_similar_memory",
    "read_similar_memory": "read_evidence_catalog",
}

ACTION_FOR_TOOL = {
    "read_recent_judgments": "investigate",
    "read_outcome_calibration": "compare_history",
    "read_similar_memory": "compare_history",
    "read_evidence_catalog": "investigate",
    "create_factor_hypothesis": "generate_factor",
}


class RuleBasedAgentProvider:
    """Deterministic local Agent policy with the same contract as the remote provider.

    It never invents facts: it only chooses the next allowed action from the
    structured judgment and the previous tool result. This keeps agent mode
    demonstrable without an API key, and gives the remote provider a baseline
    to compare against.
    """

    provider = "rule-based-agent"
    model_version = "agent-policy-v1"
    counts_model_calls = False

    def __init__(self, max_steps: int = 3):
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.max_steps = max_steps

    def decide(
        self,
        context: dict[str, Any],
        tool_result: Optional[ToolResult],
        step: int,
    ) -> AgentDecision:
        confidence = _confidence(context)
        if step == 1:
            return self._first_step(context, confidence)
        if tool_result is not None and not tool_result.ok:
            return _terminal(
                step, "finish", "工具失败，保留已有事实并结束本轮", confidence
            )
        previous = tool_result.tool_name if tool_result else ""
        if step >= self.max_steps:
            return _terminal(
                step,
                "finish",
                "研究动作已完成，生成最终报告",
                confidence,
            )
        return self._follow_up(context, tool_result, step, confidence, previous)

    def _first_step(self, context: dict[str, Any], confidence: float) -> AgentDecision:
        regime = str(context.get("regime", "unknown"))
        priority = str(context.get("research_priority", "watch"))
        if priority == "silent" or regime == "quiet":
            return _terminal(step=1, action="monitor", reason="状态平静，不需要额外研究动作", confidence=confidence)
        if regime == "insufficient_data":
            return _terminal(
                step=1,
                action="wait_for_confirmation",
                reason="关键数据缺失，等待下一帧再判断",
                confidence=confidence,
            )
        return _tool_decision(
            step=1,
            tool_name="read_recent_judgments",
            reason="状态达到研究优先级，先确认该状态在近期判断中是否持续",
            confidence=confidence,
            arguments={"limit": 12},
        )

    def _follow_up(
        self,
        context: dict[str, Any],
        tool_result: Optional[ToolResult],
        step: int,
        confidence: float,
        previous: str,
    ) -> AgentDecision:
        if previous in {"", "read_recent_judgments"}:
            candidate = _factor_candidate(context)
            if candidate is not None:
                return _tool_decision(
                    step=step,
                    tool_name="create_factor_hypothesis",
                    reason="证据关系支持把当前状态转成可验证的因子假设 {}".format(candidate),
                    confidence=confidence,
                    arguments={"name": candidate},
                )
            if _count(tool_result) >= 2:
                return _tool_decision(
                    step=step,
                    tool_name="read_outcome_calibration",
                    reason="该状态在近期判断中重复出现，检查同状态历史复盘与失效率",
                    confidence=confidence,
                )
            return _tool_decision(
                step=step,
                tool_name="read_similar_memory",
                reason="该状态是近期首次出现，检索相近历史研究上下文",
                confidence=confidence,
            )
        following = NEXT_READ.get(previous)
        if following is None:
            return _terminal(step, "finish", "没有更多可读证据，生成最终报告", confidence)
        return _tool_decision(
            step=step,
            tool_name=following,
            reason="继续读取该状态的历史证据",
            confidence=confidence,
        )


def _tool_decision(
    step: int,
    tool_name: str,
    reason: str,
    confidence: float,
    arguments: Optional[dict[str, Any]] = None,
) -> AgentDecision:
    return AgentDecision(
        step=step,
        action=AgentAction(
            action=ACTION_FOR_TOOL[tool_name],
            reason=reason,
            confidence=confidence,
            tool_name=tool_name,
            tool_args=arguments or {},
        ),
    )


def _terminal(step: int, action: str, reason: str, confidence: float) -> AgentDecision:
    return AgentDecision(
        step=step,
        action=AgentAction(action=action, reason=reason, confidence=confidence),
        finished=True,
    )


def _confidence(context: dict[str, Any]) -> float:
    try:
        value = float(context.get("confidence", 0.5))
    except (TypeError, ValueError):
        return 0.5
    return round(min(max(value, 0.0), 1.0), 4)


def _factor_candidate(context: dict[str, Any]) -> Optional[str]:
    """The first factor mapping offered for the current regime, if any.

    Workflow mode derives a hypothesis for every escalated frame that has a
    mapping, so the rule policy keeps the same coverage instead of silently
    producing fewer research artefacts than the deterministic path.
    """
    candidates = list(context.get("factor_candidates") or [])
    return str(candidates[0]) if candidates else None


def _count(tool_result: Optional[ToolResult]) -> int:
    if tool_result is None or not isinstance(tool_result.data, dict):
        return 0
    try:
        return int(tool_result.data.get("count", 0))
    except (TypeError, ValueError):
        return 0
