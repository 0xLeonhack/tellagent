import pytest

from tellagent.agent_schemas import AgentAction, AgentDecision, ToolCall
from tellagent.tools import ToolRegistry


def test_agent_action_rejects_unknown_action():
    with pytest.raises(ValueError):
        AgentAction(action="place_order", reason="bad", confidence=0.9)


def test_tool_registry_only_executes_registered_tools():
    registry = ToolRegistry()
    registry.register("read_history", "Read recent judgments", lambda args: {"count": 2})

    result = registry.execute(ToolCall(call_id="1", tool_name="read_history"))
    assert result.ok is True
    assert result.data == {"count": 2}

    rejected = registry.execute(ToolCall(call_id="2", tool_name="shell"))
    assert rejected.ok is False
    assert "Unknown tool" in rejected.error


def test_agent_decision_can_finish_without_tool():
    decision = AgentDecision(
        step=1,
        action=AgentAction(action="finish", reason="state is quiet", confidence=0.8),
        finished=True,
    )
    assert decision.finished is True
    assert decision.action.tool_name is None
