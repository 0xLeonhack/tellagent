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

    price_direction, price_strength = _price_state(
        asset.price_change_1h, price_threshold, asset.realized_volatility_6h
    )
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
    regime_scores = _regime_scores(
        price_direction, leverage_change, spot_confirmation, price_strength, data_quality
    )
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


def _regime_scores(direction, leverage, spot, strength, quality) -> dict[str, float]:
    scores = {name: 0.0 for name in (
        "quiet", "spot_confirmed_up", "spot_confirmed_down",
        "leverage_expansion_up", "leverage_expansion_down",
        "position_unwind_up", "position_unwind_down",
        "broad_participation_up", "broad_participation_down",
        "unconfirmed_move_up", "unconfirmed_move_down", "conflicting", "insufficient_data",
    )}
    if quality == "insufficient":
        scores["insufficient_data"] = 0.8
        return scores
    if direction == "flat" and leverage == "stable" and spot != "strong":
        scores["quiet"] = 0.8
        return scores
    suffix = "up" if direction == "up" else "down"
    if leverage == "expanding":
        scores["broad_participation_{}".format(suffix)] = 0.75 if spot == "strong" else 0.25
        scores["leverage_expansion_{}".format(suffix)] = 0.8 if spot != "strong" else 0.45
    elif leverage == "contracting":
        scores["position_unwind_{}".format(suffix)] = 0.8
    elif leverage == "stable" and spot == "strong":
        scores["spot_confirmed_{}".format(suffix)] = 0.8
    else:
        scores["unconfirmed_move_{}".format(suffix)] = 0.65
    if strength == "shock":
        for name in list(scores):
            if name not in {"quiet", "insufficient_data"}:
                scores[name] = min(0.95, scores[name] + 0.1)
    if spot == "strong" and leverage in {"expanding", "contracting"}:
        scores["conflicting"] = max(scores["conflicting"], 0.45)
    return scores
