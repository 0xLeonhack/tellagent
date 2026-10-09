from .schemas import ContinuousJudgment, ResearchGuidance


def build_research_guidance(judgment: ContinuousJudgment) -> ResearchGuidance:
    """Turn Jev's state into research actions, never trading instructions."""
    state = judgment.selected_value
    if state == "leverage_led":
        action = "investigate_now" if judgment.research_priority in {"significant", "urgent"} else "monitor"
        return ResearchGuidance(
            action=action,
            focus=["现货成交是否继续确认", "open interest 是否回落", "funding 是否继续极端"],
            factor_candidates=["leverage_dominance", "spot_derivatives_divergence"],
            invalidation_conditions=["现货成交持续扩大且 open interest 回落"],
        )
    if state == "spot_confirmed":
        return ResearchGuidance(
            action="monitor",
            focus=["open interest 是否加速扩张", "funding 是否进入极端区间"],
            factor_candidates=["spot_confirmation", "unlevered_price_move"],
            invalidation_conditions=["现货成交回落且 open interest 快速扩张"],
        )
    if state == "deleveraging":
        return ResearchGuidance(
            action="monitor",
            focus=["open interest 是否企稳", "价格是否重新走强"],
            factor_candidates=["deleveraging_pressure", "forced_position_reduction"],
            invalidation_conditions=["open interest 回升且价格重新走强"],
        )
    return ResearchGuidance(
        action="wait_for_confirmation",
        focus=list(judgment.missing_roles) or ["等待价格、现货和衍生品证据形成一致关系"],
        factor_candidates=[],
        invalidation_conditions=["获得完整且连续的市场状态数据"],
    )
