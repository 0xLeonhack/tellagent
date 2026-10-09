from tellagent.schemas import ContinuousJudgment
from tellagent.strategy import build_research_guidance


def test_leverage_guidance_is_research_only():
    judgment = ContinuousJudgment(
        frame_id="x", asset="ETH", as_of="t", selected_value="leverage_led",
        probabilities={"leverage_led": 0.82}, confidence=0.82,
        research_priority="significant", provider="test", model_version="test",
        latency_ms=0, created_at="t",
    )
    guidance = build_research_guidance(judgment)
    assert guidance.action == "investigate_now"
    assert "leverage_dominance" in guidance.factor_candidates
    assert all(word not in " ".join(guidance.focus) for word in ["买入", "卖出"])


def test_uncertain_guidance_waits_for_confirmation():
    judgment = ContinuousJudgment(
        frame_id="x", asset="BTC", as_of="t", selected_value="uncertain",
        probabilities={"uncertain": 0.62}, confidence=0.62,
        research_priority="watch", missing_roles=["open interest"],
        provider="test", model_version="test", latency_ms=0, created_at="t",
    )
    assert build_research_guidance(judgment).action == "wait_for_confirmation"
