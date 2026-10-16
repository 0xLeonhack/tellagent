from tellagent.agent_policy import RuleBasedAgentProvider
from tellagent.agent_schemas import ToolResult


def _result(tool_name, data, ok=True):
    return ToolResult(call_id="1", tool_name=tool_name, ok=ok, data=data)


def test_rule_policy_stays_quiet_for_low_priority_state():
    decision = RuleBasedAgentProvider().decide(
        {"regime": "quiet", "research_priority": "silent", "confidence": 0.75}, None, 1
    )
    assert decision.action.action == "monitor"
    assert decision.action.tool_name is None
    assert decision.finished is True


def test_rule_policy_waits_when_data_is_missing():
    decision = RuleBasedAgentProvider().decide(
        {"regime": "insufficient_data", "research_priority": "watch", "confidence": 0.3}, None, 1
    )
    assert decision.action.action == "wait_for_confirmation"
    assert decision.finished is True


def test_rule_policy_reads_history_then_proposes_factor_then_finishes():
    provider = RuleBasedAgentProvider(max_steps=3)
    context = {
        "regime": "leverage_expansion_up",
        "research_priority": "significant",
        "confidence": 0.72,
        "factor_candidates": ["leverage_dominance"],
    }
    first = provider.decide(context, None, 1)
    assert first.action.tool_name == "read_recent_judgments"
    assert first.action.action == "investigate"

    second = provider.decide(context, _result("read_recent_judgments", {"count": 1}), 2)
    assert second.action.action == "generate_factor"
    assert second.action.tool_args == {"name": "leverage_dominance"}

    third = provider.decide(
        context,
        _result("create_factor_hypothesis", {"created": True, "hypothesis_id": "ETH:x:y"}),
        3,
    )
    assert third.action.action == "finish"
    assert third.finished is True


def test_rule_policy_reads_similar_memory_without_factor_candidates():
    provider = RuleBasedAgentProvider(max_steps=3)
    context = {"regime": "spot_confirmed_up", "research_priority": "watch", "confidence": 0.6}
    provider.decide(context, None, 1)
    second = provider.decide(context, _result("read_recent_judgments", {"count": 1}), 2)
    assert second.action.tool_name == "read_similar_memory"


def test_rule_policy_uses_calibration_for_repeated_states():
    provider = RuleBasedAgentProvider(max_steps=3)
    context = {"regime": "quiet", "research_priority": "watch", "confidence": 0.6}
    second = provider.decide(context, _result("read_recent_judgments", {"count": 4}), 2)
    assert second.action.tool_name == "read_outcome_calibration"


def test_rule_policy_proposes_a_factor_even_at_watch_priority():
    provider = RuleBasedAgentProvider(max_steps=3)
    context = {
        "regime": "spot_confirmed_down",
        "research_priority": "watch",
        "confidence": 0.58,
        "factor_candidates": ["spot_confirmation", "unlevered_price_move"],
    }
    decision = provider.decide(context, _result("read_recent_judgments", {"count": 1}), 2)
    assert decision.action.action == "generate_factor"
    assert decision.action.tool_name == "create_factor_hypothesis"
    assert decision.action.tool_args == {"name": "spot_confirmation"}


def test_rule_policy_uses_spare_steps_for_deeper_reads():
    provider = RuleBasedAgentProvider(max_steps=4)
    context = {
        "regime": "leverage_expansion_up",
        "research_priority": "significant",
        "confidence": 0.7,
        "factor_candidates": ["leverage_dominance"],
    }
    third = provider.decide(
        context, _result("create_factor_hypothesis", {"created": True}), 3
    )
    assert third.action.tool_name == "read_outcome_calibration"

    fourth = provider.decide(
        context, _result("read_outcome_calibration", {"available": True}), 4
    )
    assert fourth.action.action == "finish"


def test_rule_policy_stops_after_a_failed_tool():
    provider = RuleBasedAgentProvider(max_steps=3)
    decision = provider.decide(
        {"regime": "quiet", "research_priority": "watch", "confidence": 0.5},
        _result("read_recent_judgments", None, ok=False),
        2,
    )
    assert decision.action.action == "finish"
    assert "工具失败" in decision.action.reason


def test_rule_policy_finishes_on_the_last_step():
    provider = RuleBasedAgentProvider(max_steps=2)
    decision = provider.decide(
        {"regime": "quiet", "research_priority": "watch", "confidence": 0.5},
        _result("read_recent_judgments", {"count": 1}),
        2,
    )
    assert decision.action.action == "finish"
