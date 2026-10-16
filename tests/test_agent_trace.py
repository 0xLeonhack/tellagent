from pathlib import Path

from tellagent.agent_schemas import AgentAction, AgentDecision, AgentRunSummary, AgentTrace
from tellagent.agent_trace import JsonlAgentTraceStore, summarize_agent_runs


def _summary(
    asset="ETH",
    as_of="2026-10-08T00:00:00Z",
    terminal="finish",
    actions=("investigate", "finish"),
    tools=("read_recent_judgments",),
    failed=(),
    model_calls=2,
):
    decisions = []
    for index, action in enumerate(actions, start=1):
        decisions.append(AgentDecision(
            step=index,
            action=AgentAction(
                action=action,
                reason="test",
                confidence=0.6,
                tool_name=tools[index - 1] if index - 1 < len(tools) else None,
            ),
            finished=index == len(actions),
        ))
    trace = AgentTrace(trace_id="{}:frame".format(asset), frame_id="frame", decisions=decisions)
    return AgentRunSummary(
        trace_id=trace.trace_id,
        frame_id="frame",
        asset=asset,
        as_of=as_of,
        provider="rule-based-observer",
        model_version="market-state-v2",
        context_state="leverage_expansion_up",
        research_priority="significant",
        decision_provider="rule-based-agent",
        steps=len(decisions),
        model_calls=model_calls,
        actions=list(actions),
        tool_names=list(tools),
        failed_tools=list(failed),
        terminal_action=terminal,
        terminal_reason="test",
        terminal_within_budget=True,
        confidence=0.6,
        factor_hypothesis_ids=[],
        created_at=as_of,
        trace=trace,
    )


def test_trace_store_appends_and_replays_by_asset(tmp_path: Path):
    store = JsonlAgentTraceStore(tmp_path)
    store.append(_summary(asset="ETH"))
    store.append(_summary(asset="BTC"))

    assert [item.asset for item in store.summaries()] == ["ETH", "BTC"]
    eth = store.summaries("eth")
    assert len(eth) == 1
    assert eth[0].trace.decisions[-1].action.action == "finish"
    assert (tmp_path / "agent_traces" / "2026-10-08.jsonl").exists()


def test_trace_stats_summarize_actions_and_tool_success():
    stats = summarize_agent_runs([
        _summary(terminal="finish", actions=("investigate", "finish"), model_calls=2),
        _summary(terminal="monitor", actions=("monitor",), tools=(), model_calls=0),
        _summary(
            terminal="finish",
            actions=("investigate", "compare_history", "finish"),
            tools=("read_recent_judgments", "read_similar_memory"),
            failed=("read_similar_memory",),
            model_calls=3,
        ),
    ])
    assert stats.run_count == 3
    assert stats.average_steps == 2.0
    assert stats.average_model_calls == 1.6667
    assert stats.finish_rate == 0.6667
    assert stats.action_counts["investigate"] == 2
    assert stats.tool_counts["read_recent_judgments"] == 2
    assert stats.terminal_counts == {"finish": 2, "monitor": 1}
    assert stats.tool_success_rate == 0.6667


def test_trace_stats_are_empty_without_runs():
    stats = summarize_agent_runs([])
    assert stats.run_count == 0
    assert stats.finish_rate == 0.0
    assert stats.action_counts == {}
