from typing import List

from .schemas import AssetSnapshot, EvidenceBundle, SnapshotAnalysis


def _percent(value: float) -> str:
    return "{:.2f}%".format(value * 100)


def analyze_asset(asset: AssetSnapshot) -> SnapshotAnalysis:
    supporting: List[str] = []
    contradicting: List[str] = []
    missing: List[str] = []
    quality_notes: List[str] = []

    price = asset.price_change_1h
    volume = asset.spot_volume_change_1h
    funding = asset.funding_rate
    oi = asset.open_interest_change_1h

    if price is None:
        missing.append("缺少 1h 价格变化")
    elif price > 0.02:
        supporting.append("价格 1h 上涨 {}".format(_percent(price)))
    elif price < -0.02:
        supporting.append("价格 1h 下跌 {}".format(_percent(abs(price))))
    else:
        quality_notes.append("价格变化未达到明显趋势阈值")

    if volume is None:
        missing.append("缺少现货成交量变化")
    elif volume > 0.05:
        supporting.append("现货成交量明显增加 {}".format(_percent(volume)))
    elif price is not None and price > 0.02:
        contradicting.append("现货成交量仅变化 {}，未充分确认上涨".format(_percent(volume)))

    if funding is None:
        missing.append("缺少 funding rate")
    elif funding > 0.0002:
        supporting.append("funding rate 偏高 ({:.4f}%)".format(funding * 100))
    elif funding < -0.0002:
        supporting.append("funding rate 偏低 ({:.4f}%)".format(funding * 100))

    if oi is None:
        missing.append("缺少 open interest 变化")
    elif oi > 0.08:
        supporting.append("open interest 快速增加 {}".format(_percent(oi)))
    elif oi < -0.08:
        supporting.append("open interest 快速下降 {}".format(_percent(abs(oi))))

    leverage_led = (
        price is not None and price > 0.02 and oi is not None and oi > 0.08
        and (volume is None or volume < oi * 0.75)
    )
    spot_confirmed = (
        price is not None and price > 0.02 and volume is not None and volume > 0.05
        and (oi is None or oi <= 0.12)
    )
    deleveraging = (
        price is not None and price < -0.02 and oi is not None and oi < -0.08
    )

    if leverage_led:
        suggested_state = "leverage_led"
        headline = "上涨可能主要由杠杆推动，现货确认不足"
    elif spot_confirmed:
        suggested_state = "spot_confirmed"
        headline = "价格上涨得到现货成交确认"
    elif deleveraging:
        suggested_state = "deleveraging"
        headline = "下跌伴随持仓收缩，市场可能正在去杠杆"
    else:
        suggested_state = "uncertain"
        headline = "证据不足，暂时无法确认主导市场状态"

    if suggested_state == "leverage_led":
        contradicting.append("如果现货成交同步持续放大，则杠杆主导解释会减弱")
        invalidation = "若现货成交继续扩大且 open interest 回落，当前判断应失效。"
    elif suggested_state == "spot_confirmed":
        contradicting.append("open interest 若突然快速扩张，仍需警惕杠杆推动")
        invalidation = "若现货成交回落而 open interest 快速扩张，现货确认判断应降级。"
    elif suggested_state == "deleveraging":
        contradicting.append("如果价格快速收复且现货成交放大，去杠杆解释会减弱")
        invalidation = "若 open interest 回升且价格重新走强，当前去杠杆判断应失效。"
    else:
        contradicting.append("当前没有足够的跨指标证据支持单一市场叙事")
        invalidation = "获得连续的价格、现货和衍生品数据后再更新判断。"

    if not supporting:
        supporting.append("未发现足够的支持证据")
    if not missing:
        missing.append("未接入链上数据，链上确认仍然缺失")

    confidence = 0.45
    if suggested_state in {"leverage_led", "spot_confirmed", "deleveraging"}:
        confidence = min(0.92, 0.55 + 0.08 * len(supporting) - 0.04 * len(missing))

    return SnapshotAnalysis(
        asset=asset,
        evidence=EvidenceBundle(
            supporting=supporting,
            contradicting=contradicting,
            missing=missing,
        ),
        suggested_state=suggested_state,
        quality_notes=quality_notes,
    )


def analysis_fields(analysis: SnapshotAnalysis):
    """Return derived report fields without putting presentation into the schema."""
    state = analysis.suggested_state
    if state == "leverage_led":
        headline = "上涨可能主要由杠杆推动，现货确认不足"
        invalidation = "若现货成交继续扩大且 open interest 回落，当前判断应失效。"
        confidence = min(0.92, 0.55 + 0.08 * len(analysis.evidence.supporting) - 0.04 * len(analysis.evidence.missing))
    elif state == "spot_confirmed":
        headline = "价格上涨得到现货成交确认"
        invalidation = "若现货成交回落而 open interest 快速扩张，现货确认判断应降级。"
        confidence = min(0.92, 0.55 + 0.08 * len(analysis.evidence.supporting) - 0.04 * len(analysis.evidence.missing))
    elif state == "deleveraging":
        headline = "下跌伴随持仓收缩，市场可能正在去杠杆"
        invalidation = "若 open interest 回升且价格重新走强，当前去杠杆判断应失效。"
        confidence = min(0.92, 0.55 + 0.08 * len(analysis.evidence.supporting) - 0.04 * len(analysis.evidence.missing))
    else:
        headline = "证据不足，暂时无法确认主导市场状态"
        invalidation = "获得连续的价格、现货和衍生品数据后再更新判断。"
        confidence = 0.45
    return headline, invalidation, confidence
