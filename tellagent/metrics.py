from typing import List, Optional, Tuple

from .schemas import AssetSnapshot, EvidenceBundle, MarketReport, MarketSnapshot, SnapshotAnalysis


OI_1H_THRESHOLD = 0.08
OI_INTERVAL_THRESHOLD = 0.015


def _percent(value: float) -> str:
    return "{:.2f}%".format(value * 100)


def oi_signal(oi_1h: Optional[float], oi_interval: Optional[float]) -> Tuple[Optional[float], float]:
    """Return the OI change to use and its threshold; 1h is preferred over the interval."""
    if oi_1h is not None:
        return oi_1h, OI_1H_THRESHOLD
    return oi_interval, OI_INTERVAL_THRESHOLD


def classify_state(
    price: Optional[float],
    volume: Optional[float],
    oi: Optional[float],
    oi_threshold: float,
) -> str:
    """Single source of truth for the four market states, shared by metrics and Observer."""
    if (
        price is not None and price > 0.02 and oi is not None and oi > oi_threshold
        and (volume is None or volume < oi * 0.75)
    ):
        return "leverage_led"
    if (
        price is not None and price > 0.02 and volume is not None and volume > 0.05
        and (oi is None or oi <= oi_threshold)
    ):
        return "spot_confirmed"
    if price is not None and price < -0.02 and oi is not None and oi < -oi_threshold:
        return "deleveraging"
    return "uncertain"


def analyze_asset(asset: AssetSnapshot) -> SnapshotAnalysis:
    price = asset.price_change_1h
    volume = asset.spot_volume_change_1h
    oi, oi_threshold = oi_signal(asset.open_interest_change_1h, asset.open_interest_change_interval)
    oi_window = "1h" if asset.open_interest_change_1h is not None else "本轮"
    missing = _missing_evidence(asset)
    state = classify_state(price, volume, oi, oi_threshold)
    if state == "leverage_led":
        supporting, contradicting = _leverage_evidence(asset, oi, oi_window)
    elif state == "spot_confirmed":
        supporting, contradicting = _spot_evidence(asset)
    elif state == "deleveraging":
        supporting, contradicting = _deleveraging_evidence(asset, oi, oi_window)
    else:
        supporting = ["未发现足够的跨指标证据支持单一市场状态"]
        contradicting = _uncertain_evidence(asset)

    if not contradicting:
        contradicting.append("当前数据中未发现明确的反向证据")
    missing.append("未接入链上数据，链上确认仍然缺失")

    return SnapshotAnalysis(
        asset=asset,
        evidence=EvidenceBundle(
            supporting=supporting,
            contradicting=contradicting,
            missing=missing,
        ),
        suggested_state=state,
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


def _spot_evidence(asset: AssetSnapshot) -> Tuple[List[str], List[str]]:
    supporting = [
        "价格 1h 上涨 {}".format(_percent(asset.price_change_1h)),
        "现货成交量明显增加 {}".format(_percent(asset.spot_volume_change_1h)),
    ]
    contradicting: List[str] = []
    if asset.funding_rate is not None and asset.funding_rate > 0.0002:
        contradicting.append("funding rate 同时偏高 ({:.4f}%)".format(asset.funding_rate * 100))
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
