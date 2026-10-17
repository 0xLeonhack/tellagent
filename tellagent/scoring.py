"""Evidence-weighted regime scoring.

The rule table in :mod:`assessment` decides the *primary* label. This module
turns the same evidence into a full distribution over all regimes, so downstream
code can distinguish "a weak watch" from "a decisive conflict" instead of
reading a one-hot label.

The scores are **not** statistically calibrated probabilities. They are bounded
evidence weights normalised through a softmax, and ``confidence`` is a separate
function of the margin and data quality. Every constant below is a documented
design choice; ``docs/ACCURACY.md`` records how they were checked against
historical data.
"""

import math
from dataclasses import dataclass
from typing import Dict, Mapping, Optional

from .schemas import AssetSnapshot

REGIMES = (
    "quiet",
    "spot_confirmed_up",
    "spot_confirmed_down",
    "leverage_expansion_up",
    "leverage_expansion_down",
    "position_unwind_up",
    "position_unwind_down",
    "broad_participation_up",
    "broad_participation_down",
    "unconfirmed_move_up",
    "unconfirmed_move_down",
    "conflicting",
    "insufficient_data",
)

# Derived from 30 days of Coinbase hourly candles (BTC and ETH) and Deribit
# funding history; docs/ACCURACY.md records the measured quantiles. These are
# warm-up defaults: after enough samples the asset's own rolling p90 takes over.
DEFAULT_PRICE_THRESHOLD = 0.006        # ~p92-p95 of hourly |return| (pooled)
DEFAULT_VOLUME_THRESHOLD = 0.8         # ~p87 of hourly |volume change| (pooled)
DEFAULT_OI_INTERVAL_THRESHOLD = 0.015  # per-hour rate
DEFAULT_OI_1H_THRESHOLD = 0.08
FUNDING_EXTREME = 0.00012              # ~p93-p95 of |8h funding| (pooled)

SPOT_STRENGTH = {"strong": 1.0, "weak": 0.35, "absent": 0.0, "unknown": 0.0}

# The rule label is the deterministic decision. The bonus keeps it as the argmax
# while still letting near-miss hypotheses carry visible probability mass.
LABEL_BONUS = 0.45
CONFIDENCE_CAP = 0.85


@dataclass(frozen=True)
class Evidence:
    """Normalised evidence for one frame.

    ``*_z`` values are the observed change divided by the applicable threshold,
    clipped so that a single outlier cannot dominate the distribution.
    """

    price_z: float
    volume_z: float
    oi_z: float
    funding_z: float
    volume_ratio: float
    activity: float
    spot_strength: float
    leverage: str
    funding_crowded: bool
    alignment: str
    quality: float
    critical_missing: int
    direction: str
    strength: str
    regime: str


def build_evidence(
    asset: AssetSnapshot,
    *,
    direction: str,
    strength: str,
    leverage: str,
    spot_confirmation: str,
    funding_state: str,
    alignment: str,
    quality: float,
    regime: str,
    oi_change: Optional[float],
    oi_threshold: float,
) -> Evidence:
    """Normalise raw asset fields into comparable evidence magnitudes."""
    thresholds = asset.strategy_thresholds or {}
    price_threshold = max(thresholds.get("price_change_1h", DEFAULT_PRICE_THRESHOLD), 1e-9)
    volume_threshold = max(thresholds.get("spot_volume_change_1h", DEFAULT_VOLUME_THRESHOLD), 1e-9)
    oi_threshold = max(oi_threshold, 1e-9)

    price = asset.price_change_1h or 0.0
    volume = asset.spot_volume_change_1h or 0.0
    oi = oi_change or 0.0
    funding = asset.funding_rate or 0.0
    funding_threshold = max(
        thresholds.get("funding_extreme", FUNDING_EXTREME), 1e-9
    )
    price_z = _clip(price / price_threshold, -3.0, 3.0)
    volume_z = _clip(volume / volume_threshold, -2.0, 4.0)
    oi_z = _clip(oi / oi_threshold, -3.0, 3.0)
    funding_z = _clip(funding / funding_threshold, -3.0, 3.0)
    volume_ratio = asset.spot_volume_ratio_6h
    if volume_ratio is None:
        volume_ratio = max(0.2, 1.0 + volume)
    activity = 1.0 - math.exp(
        -(
            0.85 * min(abs(price_z), 3.0)
            + 0.40 * max(volume_z, 0.0)
            + 0.60 * min(abs(oi_z), 3.0)
            + 0.35 * max(math.log(max(volume_ratio, 1e-9)), 0.0)
        )
        / 2.0
    )
    return Evidence(
        price_z=price_z,
        volume_z=volume_z,
        oi_z=oi_z,
        funding_z=funding_z,
        volume_ratio=volume_ratio,
        activity=activity,
        spot_strength=SPOT_STRENGTH.get(spot_confirmation, 0.0),
        leverage=leverage,
        funding_crowded=funding_state in {"long_crowded", "short_crowded"},
        alignment=alignment,
        quality=_clip(quality, 0.0, 1.0),
        # Only price and open interest make a regime unidentifiable. Missing
        # volume degrades confidence (quality is lowered) but still leaves the
        # price/OI relationship readable.
        critical_missing=sum(
            1 for value in (asset.price_change_1h, oi_change) if value is None
        ),
        direction=direction,
        strength=strength,
        regime=regime,
    )


def score_regimes(evidence: Evidence) -> Dict[str, float]:
    """Return a softmax distribution over all regimes."""
    logits = _logits(evidence)
    return _softmax(logits)


def score_confidence(probabilities: Mapping[str, float], evidence: Evidence) -> float:
    """Confidence that the primary regime explains the frame.

    It measures the *relative* margin between the top two hypotheses, scaled by
    data quality and discounted when evidence roles conflict. It is capped so a
    heuristic score never claims certainty.
    """
    ranked = sorted(probabilities.values(), reverse=True)
    top = ranked[0] if ranked else 0.0
    runner_up = ranked[1] if len(ranked) > 1 else 0.0
    margin = (top - runner_up) / max(top, 1e-9)
    quality_factor = 0.55 + 0.45 * evidence.quality
    conflict_factor = 0.85 if evidence.alignment == "conflicting" else 1.0
    value = (0.35 + 0.50 * margin) * quality_factor * conflict_factor
    return round(min(CONFIDENCE_CAP, max(0.05, value)), 4)


def _logits(evidence: Evidence) -> Dict[str, float]:
    price_energy = min(abs(evidence.price_z), 2.0)
    oi_energy = min(abs(evidence.oi_z), 2.0)
    # A directional hypothesis is only plausible when price actually moved.
    # Without this gate every quiet frame leaks mass into spot_confirmed_*.
    direction_gate = min(1.0, abs(evidence.price_z) / 0.75)
    spot = evidence.spot_strength
    spot_not_strong = 1.0 - spot
    expanding = 1.0 if evidence.leverage == "expanding" else 0.0
    contracting = 1.0 if evidence.leverage == "contracting" else 0.0
    stable = 1.0 if evidence.leverage == "stable" else 0.0

    logits = {
        "quiet": 1.60 - 3.20 * evidence.activity,
        "conflicting": (
            -0.60
            + 1.10 * (1.0 if evidence.alignment == "conflicting" else 0.0)
            + 0.70 * (1.0 if spot >= 1.0 and evidence.leverage != "stable" else 0.0)
            + 0.50 * evidence.activity
            + 0.30 * (1.0 if evidence.funding_crowded else 0.0)
            + 0.20 * min(abs(evidence.funding_z), 2.0)
        ),
        # Missing open interest is not a small perturbation: every leverage
        # regime becomes unidentifiable, so the data hypothesis must win.
        "insufficient_data": (
            2.40 * (1.0 - evidence.quality) - 0.40 + 0.80 * evidence.critical_missing
        ),
    }
    for suffix, matches in (("up", evidence.direction == "up"), ("down", evidence.direction == "down")):
        direction_match = 1.0 if matches else 0.0
        penalty = 1.20 * max(abs(evidence.price_z) - 0.25, 0.0) * (1.0 - direction_match)
        logits["spot_confirmed_{}".format(suffix)] = _directional_logit(
            direction_match, direction_gate, penalty,
            1.50 * direction_match + 0.55 * price_energy + 1.10 * spot + 0.90 * stable,
        )
        logits["leverage_expansion_{}".format(suffix)] = _directional_logit(
            direction_match, direction_gate, penalty,
            1.45 * direction_match + 0.55 * price_energy
            + 1.15 * expanding + 0.65 * spot_not_strong + 0.55 * oi_energy
            + 0.30 * min(abs(evidence.funding_z), 2.0),
        )
        logits["position_unwind_{}".format(suffix)] = _directional_logit(
            direction_match, direction_gate, penalty,
            1.40 * direction_match + 0.50 * price_energy
            + 1.20 * contracting + 0.45 * oi_energy,
        )
        logits["broad_participation_{}".format(suffix)] = _directional_logit(
            direction_match, direction_gate, penalty,
            1.45 * direction_match + 0.50 * price_energy
            + 1.00 * expanding + 1.00 * spot
            + 0.45 * (price_energy + oi_energy) / 2.0
            + 0.30 * min(abs(evidence.funding_z), 2.0),
        )
        logits["unconfirmed_move_{}".format(suffix)] = _directional_logit(
            direction_match, direction_gate, penalty,
            1.40 * direction_match + 0.60 * price_energy
            + 0.95 * stable + 0.70 * spot_not_strong,
        )
    # The rule table owns the primary label. The bonus keeps near-miss
    # hypotheses visible, and the floor guarantees the label is still the
    # argmax even for pathological evidence combinations.
    label = evidence.regime
    rival = max(value for name, value in logits.items() if name != label)
    logits[label] = max(logits[label] + LABEL_BONUS, rival + 1e-3)
    return logits


def _directional_logit(direction_match: float, gate: float, penalty: float, evidence: float) -> float:
    return -1.60 + gate * evidence - penalty


def _softmax(logits: Mapping[str, float]) -> Dict[str, float]:
    peak = max(logits.values())
    weights = {name: math.exp(value - peak) for name, value in logits.items()}
    total = sum(weights.values())
    scores = {name: round(weight / total, 6) for name, weight in weights.items()}
    # Rounding must never make the distribution drift away from 1.0.
    drift = round(1.0 - sum(scores.values()), 6)
    if drift:
        leader = max(scores, key=scores.get)
        scores[leader] = round(scores[leader] + drift, 6)
    return scores


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
