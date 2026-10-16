from .metrics import REPORT_TEXT
from .schemas import ContinuousJudgment, ResearchGuidance


def build_research_guidance(judgment: ContinuousJudgment) -> ResearchGuidance:
    state = judgment.selected_value
    invalidation = [REPORT_TEXT[state][1]]
    if state.startswith("leverage_expansion"):
        return ResearchGuidance(
            action="investigate_now" if judgment.research_priority in {"significant", "urgent"} else "monitor",
            focus=["现货成交是否形成确认", "open interest 是否继续扩张", "funding 是否继续拥挤"],
            factor_candidates=["leverage_dominance", "spot_derivatives_divergence"],
            invalidation_conditions=invalidation,
        )
    if state.startswith("spot_confirmed"):
        return ResearchGuidance(
            action="monitor",
            focus=["现货成交是否持续", "open interest 是否脱离稳定区间"],
            factor_candidates=["spot_confirmation", "unlevered_price_move"],
            invalidation_conditions=invalidation,
        )
    if state.startswith("position_unwind"):
        return ResearchGuidance(
            action="investigate_now" if judgment.research_priority in {"significant", "urgent"} else "monitor",
            focus=["open interest 是否企稳", "价格方向是否反转", "现货活动是否给出替代解释"],
            factor_candidates=["deleveraging_pressure", "forced_position_reduction"],
            invalidation_conditions=invalidation,
        )
    if state.startswith("broad_participation"):
        return ResearchGuidance(
            action="monitor",
            focus=["现货和杠杆参与是否同步持续", "funding 是否转为拥挤"],
            factor_candidates=["spot_confirmation", "leverage_dominance"],
            invalidation_conditions=invalidation,
        )
    if state.startswith("unconfirmed_move"):
        return ResearchGuidance(
            action="investigate_now" if judgment.research_priority in {"significant", "urgent"} else "monitor",
            focus=["等待现货或杠杆给出方向确认", "检查价格变化是否回归平静区间"],
            factor_candidates=["spot_derivatives_divergence"],
            invalidation_conditions=invalidation,
        )
    if state == "conflicting":
        return ResearchGuidance(
            action="investigate_now" if judgment.research_priority in {"significant", "urgent"} else "monitor",
            focus=["识别现货与杠杆证据的分歧来源", "等待驱动关系重新对齐"],
            factor_candidates=["spot_derivatives_divergence"],
            invalidation_conditions=invalidation,
        )
    if state == "quiet":
        return ResearchGuidance(
            action="monitor",
            focus=["等待价格或市场参与度突破历史阈值"],
            factor_candidates=[],
            invalidation_conditions=invalidation,
        )
    return ResearchGuidance(
        action="wait_for_confirmation",
        focus=list(judgment.missing_roles) or ["等待关键市场数据恢复"],
        factor_candidates=[],
        invalidation_conditions=invalidation,
    )
