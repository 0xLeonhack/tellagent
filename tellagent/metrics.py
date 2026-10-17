from typing import List, Tuple

from .assessment import assess_market, oi_signal
from .evidence import build_evidence_catalog
from .schemas import (
    AssetSnapshot,
    ContinuousJudgment,
    EvidenceBundle,
    MarketAssessment,
    MarketReport,
    MarketSnapshot,
    SnapshotAnalysis,
)


def _percent(value: float) -> str:
    return "{:.2f}%".format(value * 100)


def analyze_asset(
    asset: AssetSnapshot,
    data_quality_score: float = 1.0,
    source_alignment_seconds: int | None = None,
    assessment: MarketAssessment | None = None,
) -> SnapshotAnalysis:
    assessment = assessment or assess_market(asset, data_quality_score, source_alignment_seconds)
    supporting = _supporting_evidence(asset, assessment)
    contradicting = _contradicting_evidence(asset, assessment)
    missing = _missing_evidence(asset)
    if not supporting:
        supporting.append("当前没有足够证据支持单一驱动机制")
    if not contradicting:
        contradicting.append("当前数据中未发现明确的反向证据")
    return SnapshotAnalysis(
        asset=asset,
        evidence=EvidenceBundle(
            supporting=supporting,
            contradicting=contradicting,
            missing=missing,
        ),
        suggested_state=assessment.regime,
        assessment=assessment,
    )


def _supporting_evidence(asset: AssetSnapshot, assessment) -> List[str]:
    evidence = []
    if asset.price_change_1h is not None:
        if assessment.price_direction == "up":
            evidence.append("价格 1h 上涨 {}".format(_percent(asset.price_change_1h)))
        elif assessment.price_direction == "down":
            evidence.append("价格 1h 下跌 {}".format(_percent(abs(asset.price_change_1h))))
        else:
            evidence.append("价格 1h 变化 {}，处于平静区间".format(_percent(asset.price_change_1h)))
    oi, _ = oi_signal(asset)
    oi_window = "1h" if asset.open_interest_change_1h is not None else "本轮"
    if oi is not None:
        if assessment.leverage_change == "expanding":
            evidence.append("open interest {} 增加 {}".format(oi_window, _percent(oi)))
        elif assessment.leverage_change == "contracting":
            evidence.append("open interest {} 下降 {}".format(oi_window, _percent(abs(oi))))
        else:
            evidence.append("open interest {} 变化 {}，杠杆基本稳定".format(oi_window, _percent(oi)))
    if asset.spot_volume_change_1h is not None:
        if assessment.spot_confirmation == "strong":
            evidence.append("现货成交量 1h 增加 {}，形成强确认".format(_percent(asset.spot_volume_change_1h)))
        elif assessment.spot_confirmation == "weak":
            evidence.append("现货成交量 1h 仅增加 {}，确认较弱".format(_percent(asset.spot_volume_change_1h)))
        else:
            evidence.append("现货成交量 1h 变化 {}，未形成确认".format(_percent(asset.spot_volume_change_1h)))
    if asset.funding_rate is not None and assessment.funding_state != "neutral":
        evidence.append("funding rate 为 {:.4f}%，状态为 {}".format(
            asset.funding_rate * 100, assessment.funding_state
        ))
    return evidence


def _contradicting_evidence(asset: AssetSnapshot, assessment) -> List[str]:
    evidence = []
    if assessment.regime.startswith("leverage_expansion") and assessment.spot_confirmation != "strong":
        evidence.append("现货成交没有同步形成强确认")
    if assessment.regime.startswith("position_unwind") and assessment.spot_confirmation == "strong":
        evidence.append("现货成交活跃，仓位收缩不是唯一解释")
    if assessment.regime.startswith("spot_confirmed") and assessment.funding_state in {"long_crowded", "short_crowded"}:
        evidence.append("funding 处于拥挤状态，现货主导解释需要降级")
    if assessment.regime == "conflicting":
        evidence.append("价格、现货和杠杆证据未形成一致驱动关系")
    if assessment.regime == "insufficient_data":
        evidence.append("关键字段缺失，不能排除其他市场机制")
    return evidence


def _missing_evidence(asset: AssetSnapshot) -> List[str]:
    fields = (
        (asset.price_change_1h, "缺少 1h 价格变化"),
        (asset.price_change_6h, "缺少 6h 价格变化"),
        (asset.spot_volume_change_1h, "缺少现货成交量变化"),
        (asset.funding_rate, "缺少 funding rate"),
    )
    missing = [message for value, message in fields if value is None]
    if asset.open_interest_change_1h is None and asset.open_interest_change_interval is None:
        missing.append("缺少 open interest 变化")
    return missing


REPORT_TEXT = {
    "quiet": ("市场处于低活动状态", "若价格、现货或杠杆活动突破历史阈值，应重新判断。"),
    "spot_confirmed_up": ("上涨得到现货成交确认，杠杆变化有限", "若现货成交回落或杠杆快速扩张，现货确认判断应失效。"),
    "spot_confirmed_down": ("下跌得到现货成交确认，杠杆变化有限", "若现货成交回落或杠杆快速扩张，现货确认判断应失效。"),
    "leverage_expansion_up": ("上涨伴随杠杆扩张，现货确认不足", "若现货成交形成强确认或 open interest 回落，当前判断应失效。"),
    "leverage_expansion_down": ("下跌伴随杠杆扩张，需关注空头压力", "若 open interest 回落或价格快速收复，当前判断应失效。"),
    "position_unwind_up": ("上涨伴随仓位收缩，可能存在空头回补", "若 open interest 重新扩张，仓位收缩解释应失效。"),
    "position_unwind_down": ("下跌伴随仓位收缩，市场正在去杠杆", "若 open interest 回升且价格走强，去杠杆判断应失效。"),
    "broad_participation_up": ("上涨同时获得现货与杠杆参与", "若现货或杠杆任一侧快速回落，共识上涨判断应降级。"),
    "broad_participation_down": ("下跌同时伴随现货活跃与杠杆扩张", "若现货活跃或杠杆扩张消退，共识下跌判断应降级。"),
    "unconfirmed_move_up": ("价格温和上涨，但现货与杠杆均未确认", "当现货或杠杆形成明确驱动后，应替换当前判断。"),
    "unconfirmed_move_down": ("价格温和下跌，但现货与杠杆均未确认", "当现货或杠杆形成明确驱动后，应替换当前判断。"),
    "conflicting": ("市场活动明显，但证据关系相互冲突", "当现货与杠杆证据重新对齐后，应替换当前判断。"),
    "insufficient_data": ("关键证据不足，暂时无法判断市场驱动", "获得连续的价格、现货和衍生品数据后再更新判断。"),
}


def analysis_fields(analysis: SnapshotAnalysis) -> Tuple[str, str, float]:
    headline, invalidation = REPORT_TEXT[analysis.suggested_state]
    assessment = analysis.assessment
    confidence = 0.35
    if assessment.data_quality == "complete":
        confidence += 0.15
    if assessment.alignment == "aligned":
        confidence += 0.15
    if assessment.price_strength == "shock":
        confidence += 0.1
    if assessment.regime in {"quiet", "insufficient_data"}:
        confidence = 0.55 if assessment.regime == "quiet" else 0.3
    return headline, invalidation, round(min(confidence, 0.9), 2)


def build_deterministic_report(
    snapshot: MarketSnapshot,
    asset: AssetSnapshot,
    judgment: ContinuousJudgment | None = None,
    assessment: MarketAssessment | None = None,
) -> MarketReport:
    """Build a report without reclassifying a frozen historical frame."""
    analysis = analyze_asset(asset, assessment=assessment)
    if judgment is None:
        headline, invalidation, confidence = analysis_fields(analysis)
        state = analysis.suggested_state
    else:
        state = judgment.selected_value
        headline, invalidation = REPORT_TEXT[state]
        confidence = judgment.confidence
        if judgment.invalidation_conditions:
            invalidation = judgment.invalidation_conditions[0]
    catalog = build_evidence_catalog(asset.symbol, analysis.evidence)
    return MarketReport(
        asset=asset.symbol,
        metrics=asset,
        headline=headline,
        state=state,
        confidence=confidence,
        supporting_evidence=analysis.evidence.supporting,
        contradicting_evidence=analysis.evidence.contradicting,
        missing_evidence=analysis.evidence.missing,
        supporting_evidence_ids=[item.evidence_id for item in catalog if item.role == "supporting"],
        contradicting_evidence_ids=[item.evidence_id for item in catalog if item.role == "contradicting"],
        missing_evidence_ids=[item.evidence_id for item in catalog if item.role == "missing"],
        invalidation_condition=invalidation,
        data_time=snapshot.as_of,
        sources=snapshot.sources,
    )
