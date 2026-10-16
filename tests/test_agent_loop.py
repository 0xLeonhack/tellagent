from tellagent.agent_loop import AgentLoop
from tellagent.agent_schemas import AgentAction, AgentDecision
from tellagent.tools import ToolRegistry


def test_agent_loop_executes_tool_then_finishes():
    registry = ToolRegistry()
    registry.register("history", "Read history", lambda args: {"matches": 3})
    calls = []

    def decide(context, tool_result, step):
        calls.append((step, tool_result.data if tool_result else None))
        if step == 1:
            return AgentDecision(
                step=step,
                action=AgentAction(
                    action="compare_history", reason="need context", confidence=0.8,
                    tool_name="history",
                ),
            )
        return AgentDecision(
            step=step,
            action=AgentAction(action="finish", reason="history checked", confidence=0.9),
            finished=True,
        )

    result = AgentLoop(registry, max_steps=3).run({}, decide, "trace-1", "frame-1")
    assert len(result.trace.decisions) == 2
    assert result.trace.decisions[0].tool_result.data == {"matches": 3}
    assert calls == [(1, None), (2, {"matches": 3})]


def test_agent_loop_enforces_step_budget():
    registry = ToolRegistry()

    def decide(context, tool_result, step):
        return AgentDecision(
            step=step,
            action=AgentAction(action="investigate", reason="continue", confidence=0.5),
        )

    try:
        AgentLoop(registry, max_steps=2).run({}, decide, "trace-1", "frame-1")
    except RuntimeError as exc:
        assert "max_steps" in str(exc)
    else:
        raise AssertionError("Agent loop should stop at max_steps")


def test_agent_loop_rejects_tools_on_terminal_actions():
    registry = ToolRegistry()

    def decide(context, tool_result, step):
        return AgentDecision(
            step=step,
            action=AgentAction(
                action="finish", reason="done", confidence=0.9, tool_name="shell"
            ),
        )

    try:
        AgentLoop(registry).run({}, decide, "trace-1", "frame-1")
    except ValueError as exc:
        assert "cannot invoke a tool" in str(exc)
    else:
        raise AssertionError("Terminal action must not invoke tools")
