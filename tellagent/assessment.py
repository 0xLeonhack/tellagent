from datetime import datetime

from .schemas import AssetSnapshot, MarketAssessment, MarketSnapshot
from .scoring import (
    DEFAULT_OI_1H_THRESHOLD,
    DEFAULT_OI_INTERVAL_THRESHOLD,
    DEFAULT_PRICE_THRESHOLD,
    DEFAULT_VOLUME_THRESHOLD,
    FUNDING_EXTREME as FUNDING_EXTREME_THRESHOLD,
    build_evidence,
    score_regimes,
)


SPOT_VOLUME_RATIO_STRONG = 1.5         # ~p75 of volume / 6h median volume


def assess_market(
    asset: AssetSnapshot,
    data_quality_score: float = 1.0,
    source_alignment_seconds: int | None = None,
) -> MarketAssessment:
    thresholds = asset.strategy_thresholds
    price_threshold = thresholds.get("price_change_1h", DEFAULT_PRICE_THRESHOLD)
    volume_threshold = thresholds.get("spot_volume_change_1h", DEFAULT_VOLUME_THRESHOLD)
    oi, oi_threshold = _oi_signal(asset, thresholds.get("oi_interval", DEFAULT_OI_INTERVAL_THRESHOLD))

    price_direction, price_strength = _price_state(
        asset.price_change_1h, price_threshold, asset.realized_volatility_6h
    )
    leverage_change = _leverage_state(oi, oi_threshold)
    spot_confirmation = _spot_state(
        asset.spot_volume_change_1h,
        volume_threshold,
        asset.spot_volume_ratio_6h,
    )
    funding_threshold = thresholds.get("funding_extreme", FUNDING_EXTREME_THRESHOLD)
    funding_state = _funding_state(asset.funding_rate, funding_threshold)
    data_quality = _data_quality(asset, oi, data_quality_score)
    regime, alignment = _derive_regime(
        price_direction, price_strength, leverage_change, spot_confirmation, data_quality
    )
    risk_flags = _risk_flags(
        price_strength, leverage_change, spot_confirmation, funding_state, data_quality
    )
    regime_scores = score_regimes(build_evidence(
        asset,
        direction=price_direction,
        strength=price_strength,
        leverage=leverage_change,
        spot_confirmation=spot_confirmation,
        funding_state=funding_state,
        alignment=alignment,
        quality={"complete": 1.0, "degraded": 0.7, "insufficient": 0.2}[data_quality],
        regime=regime,
        oi_change=oi,
        oi_threshold=oi_threshold,
    ))
    ranked = sorted(regime_scores.items(), key=lambda item: item[1], reverse=True)
    secondary = [name for name, score in ranked[1:3] if score >= 0.35]
    return MarketAssessment(
        price_direction=price_direction,
        price_strength=price_strength,
        leverage_change=leverage_change,
        spot_confirmation=spot_confirmation,
        funding_state=funding_state,
        alignment=alignment,
        data_quality=data_quality,
        regime=regime,
        risk_flags=risk_flags,
        data_quality_score=data_quality_score,
        source_alignment_seconds=source_alignment_seconds,
        primary_regime=regime,
        secondary_regimes=secondary,
        regime_scores=regime_scores,
    )


COINBASE_MAX_FRESH_SECONDS = 4200      # one hourly candle + 10 minutes of slack
COINBASE_MAX_DEGRADED_SECONDS = 5400   # 1.5 hourly candles
DERIBIT_MAX_FRESH_SECONDS = 300        # live ticker
DERIBIT_MAX_DEGRADED_SECONDS = 900


def assess_snapshot_quality(snapshot: MarketSnapshot, asset: AssetSnapshot) -> tuple[float, int | None]:
    """Score source freshness without confusing cadence with clock skew.

    Spot is an hourly candle series, so its newest completed candle is
    naturally up to one hour old. Derivatives is a live ticker, so it should be
    seconds old. Each source is compared with ``snapshot.as_of``; the raw
    difference between the two source timestamps is returned only for display.
    """
    as_of = _parse_time(snapshot.as_of)
    coinbase = _source_time(snapshot, "coinbase:{}".format(asset.symbol))
    deribit = _source_time(snapshot, "deribit:{}".format(asset.symbol))
    ages = {}
    for name, value in (("coinbase", coinbase), ("deribit", deribit)):
        if value is not None:
            ages[name] = max(0, int((as_of - value).total_seconds()))
    if not ages:
        return 0.5, None
    if len(ages) == 1:
        return 0.5, next(iter(ages.values()))
    alignment = int(abs((coinbase - deribit).total_seconds()))
    coinbase_score = _freshness_score(
        ages["coinbase"], COINBASE_MAX_FRESH_SECONDS, COINBASE_MAX_DEGRADED_SECONDS
    )
    deribit_score = _freshness_score(
        ages["deribit"], DERIBIT_MAX_FRESH_SECONDS, DERIBIT_MAX_DEGRADED_SECONDS
    )
    return min(coinbase_score, deribit_score), alignment


def source_max_age_seconds(snapshot: MarketSnapshot, asset: AssetSnapshot) -> int | None:
    """Age of the oldest available source relative to the snapshot time."""
    as_of = _parse_time(snapshot.as_of)
    ages = []
    for key in ("coinbase:{}".format(asset.symbol), "deribit:{}".format(asset.symbol)):
        value = _source_time(snapshot, key)
        if value is not None:
            ages.append(max(0, int((as_of - value).total_seconds())))
    return max(ages) if ages else None


def _source_time(snapshot: MarketSnapshot, key: str) -> datetime | None:
    value = snapshot.source_times.get(key)
    if value is None:
        return None
    try:
        return _parse_time(value)
    except ValueError:
        return None


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _freshness_score(age: int, fresh_seconds: int, degraded_seconds: int) -> float:
    if age <= fresh_seconds:
        return 1.0
    if age <= degraded_seconds:
        return 0.7
    return 0.25


QUALITY_WEIGHT = {"complete": 1.0, "degraded": 0.7, "insufficient": 0.2}


def assessment_evidence(asset: AssetSnapshot, assessment: MarketAssessment):
    """Rebuild the normalised evidence behind an assessment.

    Observers need the evidence magnitudes (not only the label) to score
    competing regimes and to explain confidence. Keeping this reconstruction in
    one place guarantees the observer scores exactly what the rule table saw.
    """
    oi, oi_threshold = _oi_signal(
        asset,
        asset.strategy_thresholds.get("oi_interval", DEFAULT_OI_INTERVAL_THRESHOLD),
    )
    return build_evidence(
        asset,
        direction=assessment.price_direction,
        strength=assessment.price_strength,
        leverage=assessment.leverage_change,
        spot_confirmation=assessment.spot_confirmation,
        funding_state=assessment.funding_state,
        alignment=assessment.alignment,
        quality=QUALITY_WEIGHT[assessment.data_quality],
        regime=assessment.regime,
        oi_change=oi,
        oi_threshold=oi_threshold,
    )


def oi_signal(asset: AssetSnapshot) -> tuple[float | None, float]:
    """Raw OI change and threshold, used for display and evidence text."""
    return _oi_signal(
        asset,
        asset.strategy_thresholds.get("oi_interval", DEFAULT_OI_INTERVAL_THRESHOLD),
    )


def hourly_open_interest_change(asset: AssetSnapshot) -> float | None:
    """Express the interval OI change as a per-hour rate.

    A 0.01% change over one minute and over five minutes describe very
    different leverage behaviour. Thresholds are defined per hour, so the raw
    interval change must be rescaled before comparison.
    """
    if asset.open_interest_change_1h is not None:
        return asset.open_interest_change_1h
    change = asset.open_interest_change_interval
    seconds = asset.open_interest_interval_seconds
    if change is None:
        return None
    if seconds is not None and seconds > 0:
        return change * 3600.0 / seconds
    return change


def _oi_signal(asset: AssetSnapshot, interval_threshold: float) -> tuple[float | None, float]:
    if asset.open_interest_change_1h is not None:
        return asset.open_interest_change_1h, DEFAULT_OI_1H_THRESHOLD
    return hourly_open_interest_change(asset), interval_threshold


def _price_state(
    value: float | None,
    shock_threshold: float,
    realized_volatility: float | None = None,
) -> tuple[str, str]:
    if value is None:
        return "unknown", "unknown"
    flat_threshold = min(0.0025, shock_threshold / 2)
    if abs(value) <= flat_threshold:
        return "flat", "quiet"
    direction = "up" if value > 0 else "down"
    normalized = abs(value) / realized_volatility if realized_volatility and realized_volatility > 0 else 0
    strength = "shock" if abs(value) > shock_threshold or normalized >= 2.0 else "normal"
    return direction, strength


def _leverage_state(value: float | None, threshold: float) -> str:
    if value is None:
        return "unknown"
    if value > threshold:
        return "expanding"
    if value < -threshold:
        return "contracting"
    return "stable"


def _spot_state(
    value: float | None,
    threshold: float,
    volume_ratio: float | None = None,
) -> str:
    """Classify spot participation.

    Consecutive hourly volume is noisy (median absolute change is ~31%), so a
    raw change alone is a poor confirmation signal. The ratio to the six-hour
    median is more stable, and either a high ratio or an unusually large raw
    change counts as strong participation.
    """
    if value is None:
        return "unknown"
    if value > 0 and volume_ratio is not None and volume_ratio >= SPOT_VOLUME_RATIO_STRONG:
        return "strong"
    if value > threshold:
        return "strong"
    if value > 0:
        return "weak"
    return "absent"


def _funding_state(value: float | None, threshold: float = FUNDING_EXTREME_THRESHOLD) -> str:
    if value is None:
        return "unknown"
    if value > threshold:
        return "long_crowded"
    if value < -threshold:
        return "short_crowded"
    return "neutral"


def _data_quality(asset: AssetSnapshot, oi: float | None, score: float) -> str:
    if score < 0.5:
        return "insufficient"
    if asset.price_change_1h is None or oi is None:
        return "insufficient"
    if asset.spot_volume_change_1h is None or asset.funding_rate is None:
        return "degraded"
    if score < 0.8:
        return "degraded"
    return "complete"


def _derive_regime(
    direction: str,
    strength: str,
    leverage: str,
    spot: str,
    quality: str,
) -> tuple[str, str]:
    if quality == "insufficient" or direction == "unknown" or leverage == "unknown":
        return "insufficient_data", "insufficient"
    if direction == "flat":
        if leverage == "stable" and spot != "strong":
            return "quiet", "aligned"
        return "conflicting", "conflicting"
    suffix = "up" if direction == "up" else "down"
    if leverage == "expanding":
        if spot == "strong":
            return "broad_participation_{}".format(suffix), "aligned"
        return "leverage_expansion_{}".format(suffix), "mixed"
    if leverage == "contracting":
        return "position_unwind_{}".format(suffix), "mixed" if spot == "strong" else "aligned"
    if leverage == "stable" and spot == "strong":
        return "spot_confirmed_{}".format(suffix), "aligned"
    return "unconfirmed_move_{}".format(suffix), "mixed"


def _risk_flags(
    price_strength: str,
    leverage: str,
    spot: str,
    funding: str,
    quality: str,
) -> list[str]:
    flags = []
    if price_strength == "shock":
        flags.append("price_shock")
    if leverage == "expanding" and spot != "strong":
        flags.append("spot_leverage_divergence")
    if leverage == "contracting":
        flags.append("position_unwind")
    if funding in {"long_crowded", "short_crowded"}:
        flags.append(funding)
    if quality != "complete":
        flags.append("data_{}".format(quality))
    return flags


