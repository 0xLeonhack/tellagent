from typing import List, Tuple

from .schemas import AssetSnapshot, EvidenceBundle, MarketReport, MarketSnapshot, SnapshotAnalysis


def _percent(value: float) -> str:
    return "{:.2f}%".format(value * 100)


def analyze_asset(asset: AssetSnapshot) -> SnapshotAnalysis:
    price = asset.price_change_1h
    volume = asset.spot_volume_change_1h
    oi, oi_window = _oi_change(asset)
    oi_threshold = 0.08 if oi_window == "1h" else 0.015
    missing = _missing_evidence(asset)
    quality_notes: List[str] = []
    if price is not None and -0.02 <= price <= 0.02:
        quality_notes.append("价格变化未达到明显趋势阈值")

    leverage_led = (
        price is not None and price > 0.02 and oi is not None and oi > oi_threshold
        and (volume is None or volume < oi * 0.75)
    )
    spot_confirmed = (
        price is not None and price > 0.02 and volume is not None and volume > 0.05
        and (oi is None or oi <= oi_threshold)
    )
    deleveraging = price is not None and price < -0.02 and oi is not None and oi < -oi_threshold

    if leverage_led:
        state = "leverage_led"
        supporting, contradicting = _leverage_evidence(asset, oi, oi_window)
    elif spot_confirmed:
        state = "spot_confirmed"
        supporting, contradicting = _spot_evidence(asset, oi, oi_window, oi_threshold)
    elif deleveraging:
        state = "deleveraging"
        supporting, contradicting = _deleveraging_evidence(asset, oi, oi_window)
    else:
        state = "uncertain"
        supporting = ["未发现足够的跨指标证据支持单一市场状态"]
        contradicting = _uncertain_evidence(asset)

    if not contradicting:
        contradicting.append("当前数据中未发现明确的反向证据")
    if not missing:
        missing.append("未接入链上数据，链上确认仍然缺失")

    return SnapshotAnalysis(
        asset=asset,
        evidence=EvidenceBundle(
            supporting=supporting,
            contradicting=contradicting,
            missing=missing,
        ),
        suggested_state=state,
        quality_notes=quality_notes,
    )


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


def _leverage_evidence(asset: AssetSnapshot, oi: float, oi_window: str) -> Tuple[List[str], List[str]]:
    supporting = [
        "价格 1h 上涨 {}".format(_percent(asset.price_change_1h)),
        "open interest {} 快速增加 {}".format(oi_window, _percent(oi)),
    ]
    contradicting: List[str] = []
    if asset.funding_rate is not None and asset.funding_rate > 0.0002:
        supporting.append("funding rate 偏高 ({:.4f}%)".format(asset.funding_rate * 100))
    if asset.spot_volume_change_1h is not None:
        supporting.append(
            "现货成交量变化 {}，弱于持仓增长".format(_percent(asset.spot_volume_change_1h))
        )
        if asset.spot_volume_change_1h > 0:
            contradicting.append(
                "现货成交量也增加了 {}".format(_percent(asset.spot_volume_change_1h))
            )
    return supporting, contradicting


def _spot_evidence(asset: AssetSnapshot, oi: float | None, oi_window: str, oi_threshold: float) -> Tuple[List[str], List[str]]:
    supporting = [
        "价格 1h 上涨 {}".format(_percent(asset.price_change_1h)),
        "现货成交量明显增加 {}".format(_percent(asset.spot_volume_change_1h)),
    ]
    contradicting: List[str] = []
    if asset.funding_rate is not None and asset.funding_rate > 0.0002:
        contradicting.append("funding rate 同时偏高 ({:.4f}%)".format(asset.funding_rate * 100))
    if oi is not None and oi > oi_threshold:
        contradicting.append("open interest {} 同时增加 {}".format(oi_window, _percent(oi)))
    return supporting, contradicting


def _deleveraging_evidence(asset: AssetSnapshot, oi: float, oi_window: str) -> Tuple[List[str], List[str]]:
    supporting = [
        "价格 1h 下跌 {}".format(_percent(abs(asset.price_change_1h))),
        "open interest {} 快速下降 {}".format(oi_window, _percent(abs(oi))),
    ]
    contradicting: List[str] = []
    if asset.spot_volume_change_1h is not None and asset.spot_volume_change_1h > 0.05:
        contradicting.append(
            "现货成交量增加 {}，卖压可能不只来自去杠杆".format(
                _percent(asset.spot_volume_change_1h)
            )
        )
    return supporting, contradicting


def _uncertain_evidence(asset: AssetSnapshot) -> List[str]:
    evidence: List[str] = []
    if asset.price_change_1h is not None:
        evidence.append("价格 1h 变化仅为 {}".format(_percent(asset.price_change_1h)))
    if asset.open_interest_change_1h is None and asset.open_interest_change_interval is None:
        evidence.append("缺少持仓变化，无法判断杠杆是否主导")
    return evidence or ["当前输入不足以形成可反驳的市场叙事"]


def _oi_change(asset: AssetSnapshot) -> Tuple[float | None, str]:
    if asset.open_interest_change_1h is not None:
        return asset.open_interest_change_1h, "1h"
    return asset.open_interest_change_interval, "本轮"


def analysis_fields(analysis: SnapshotAnalysis) -> Tuple[str, str, float]:
    """Return deterministic presentation fields for the selected state."""
    state = analysis.suggested_state
    values = {
        "leverage_led": (
            "上涨可能主要由杠杆推动，现货确认不足",
            "若现货成交继续扩大且 open interest 回落，当前判断应失效。",
        ),
        "spot_confirmed": (
            "价格上涨得到现货成交确认",
            "若现货成交回落而 open interest 快速扩张，现货确认判断应降级。",
        ),
        "deleveraging": (
            "下跌伴随持仓收缩，市场可能正在去杠杆",
            "若 open interest 回升且价格重新走强，当前去杠杆判断应失效。",
        ),
        "uncertain": (
            "证据不足，暂时无法确认主导市场状态",
            "获得连续的价格、现货和衍生品数据后再更新判断。",
        ),
    }
    headline, invalidation = values[state]
    if state == "uncertain":
        confidence = 0.35 if len(analysis.evidence.missing) >= 2 else 0.45
    else:
        confidence = round(
            min(
                0.92,
                0.55 + 0.08 * len(analysis.evidence.supporting)
                - 0.04 * len(analysis.evidence.missing),
            ),
            2,
        )
    return headline, invalidation, confidence


def build_deterministic_report(snapshot: MarketSnapshot, asset: AssetSnapshot) -> MarketReport:
    """Build a report from deterministic fields, used when no strong model is configured."""
    analysis = analyze_asset(asset)
    headline, invalidation, confidence = analysis_fields(analysis)
    return MarketReport(
        asset=asset.symbol,
        metrics=asset,
        headline=headline,
        state=analysis.suggested_state,
        confidence=confidence,
        supporting_evidence=analysis.evidence.supporting,
        contradicting_evidence=analysis.evidence.contradicting,
        missing_evidence=analysis.evidence.missing,
        invalidation_condition=invalidation,
        data_time=snapshot.as_of,
        sources=snapshot.sources,
    )
