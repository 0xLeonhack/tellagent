from datetime import datetime

from .schemas import AssetSnapshot, MarketAssessment, MarketSnapshot


DEFAULT_PRICE_THRESHOLD = 0.02
DEFAULT_VOLUME_THRESHOLD = 0.05
DEFAULT_OI_INTERVAL_THRESHOLD = 0.015
DEFAULT_OI_1H_THRESHOLD = 0.08
FUNDING_EXTREME_THRESHOLD = 0.0002


def assess_market(
    asset: AssetSnapshot,
    data_quality_score: float = 1.0,
    source_alignment_seconds: int | None = None,
) -> MarketAssessment:
    thresholds = asset.strategy_thresholds
    price_threshold = thresholds.get("price_change_1h", DEFAULT_PRICE_THRESHOLD)
    volume_threshold = thresholds.get("spot_volume_change_1h", DEFAULT_VOLUME_THRESHOLD)
    oi, oi_threshold = _oi_signal(asset, thresholds.get("oi_interval", DEFAULT_OI_INTERVAL_THRESHOLD))

    price_direction, price_strength = _price_state(asset.price_change_1h, price_threshold)
    leverage_change = _leverage_state(oi, oi_threshold)
    spot_confirmation = _spot_state(asset.spot_volume_change_1h, volume_threshold)
    funding_state = _funding_state(asset.funding_rate)
    data_quality = _data_quality(asset, oi, data_quality_score)
    regime, alignment = _derive_regime(
        price_direction, price_strength, leverage_change, spot_confirmation, data_quality
    )
    risk_flags = _risk_flags(
        price_strength, leverage_change, spot_confirmation, funding_state, data_quality
    )
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
    )


def assess_snapshot_quality(snapshot: MarketSnapshot, asset: AssetSnapshot) -> tuple[float, int | None]:
    """Score source freshness/alignment without changing the underlying facts."""
    times = []
    for key in ("coinbase:{}".format(asset.symbol), "deribit:{}".format(asset.symbol)):
        value = snapshot.source_times.get(key)
        if value is not None:
            times.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
    if len(times) < 2:
        return 0.5, None
    alignment = int(abs((times[0] - times[1]).total_seconds()))
    if alignment <= 300:
        return 1.0, alignment
    if alignment <= 900:
        return 0.7, alignment
    return 0.25, alignment


def oi_signal(asset: AssetSnapshot) -> tuple[float | None, float]:
    return _oi_signal(
        asset,
        asset.strategy_thresholds.get("oi_interval", DEFAULT_OI_INTERVAL_THRESHOLD),
    )


def _oi_signal(asset: AssetSnapshot, interval_threshold: float) -> tuple[float | None, float]:
    if asset.open_interest_change_1h is not None:
        return asset.open_interest_change_1h, DEFAULT_OI_1H_THRESHOLD
    return asset.open_interest_change_interval, interval_threshold


def _price_state(value: float | None, shock_threshold: float) -> tuple[str, str]:
    if value is None:
        return "unknown", "unknown"
    flat_threshold = min(0.0025, shock_threshold / 2)
    if abs(value) <= flat_threshold:
        return "flat", "quiet"
    direction = "up" if value > 0 else "down"
    strength = "shock" if abs(value) > shock_threshold else "normal"
    return direction, strength


def _leverage_state(value: float | None, threshold: float) -> str:
    if value is None:
        return "unknown"
    if value > threshold:
        return "expanding"
    if value < -threshold:
        return "contracting"
    return "stable"


def _spot_state(value: float | None, threshold: float) -> str:
    if value is None:
        return "unknown"
    if value > threshold:
        return "strong"
    if value > 0:
        return "weak"
    return "absent"


def _funding_state(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value > FUNDING_EXTREME_THRESHOLD:
        return "long_crowded"
    if value < -FUNDING_EXTREME_THRESHOLD:
        return "short_crowded"
    return "neutral"


def _data_quality(asset: AssetSnapshot, oi: float | None, score: float) -> str:
    if score < 0.5:
        return "insufficient"
    if asset.price_change_1h is None or oi is None:
        return "insufficient"
    if asset.spot_volume_change_1h is None or asset.funding_rate is None:
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
