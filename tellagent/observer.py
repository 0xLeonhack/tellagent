import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from typing import Dict, List, Protocol

import httpx

from .assessment import assess_market, assess_snapshot_quality
from .metrics import REPORT_TEXT, analyze_asset
from .schemas import AssetSnapshot, ContinuousJudgment, FeatureBaseline, MarketStateFrame, MarketSnapshot


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


class JudgmentProvider(Protocol):
    provider: str
    model_version: str

    def judge(self, frame: MarketStateFrame) -> ContinuousJudgment: ...


def build_state_frame(
    snapshot: MarketSnapshot,
    asset: AssetSnapshot,
    baseline_state: Dict[str, FeatureBaseline] | None = None,
) -> MarketStateFrame:
    quality_score, alignment_seconds = assess_snapshot_quality(snapshot, asset)
    analysis = analyze_asset(asset, quality_score, alignment_seconds)
    frame_id = sha256(
        "{}:{}:{}".format(asset.symbol, snapshot.as_of, asset.model_dump_json()).encode()
    ).hexdigest()[:16]
    return MarketStateFrame(
        frame_id=frame_id,
        asset=asset.symbol,
        as_of=snapshot.as_of,
        price_state={"change_1h": asset.price_change_1h, "change_6h": asset.price_change_6h},
        spot_state={
            "volume_change_1h": asset.spot_volume_change_1h,
            "volume_ratio_6h": asset.spot_volume_ratio_6h,
            "realized_volatility_6h": asset.realized_volatility_6h,
        },
        leverage_state={
            "funding_rate": asset.funding_rate,
            "open_interest": asset.open_interest,
            "open_interest_change_interval": asset.open_interest_change_interval,
            "open_interest_change_1h": asset.open_interest_change_1h,
        },
        anomalies=list(analysis.evidence.supporting),
        missing_inputs=list(analysis.evidence.missing),
        quality_summary={
            "source_count": str(len(snapshot.sources)),
            "missing_count": str(len(analysis.evidence.missing)),
            "status": analysis.assessment.data_quality,
            "score": "{:.2f}".format(quality_score),
            "source_alignment_seconds": str(alignment_seconds) if alignment_seconds is not None else "unknown",
        },
        baseline_state=baseline_state or {},
        strategy_thresholds=asset.strategy_thresholds,
        assessment=analysis.assessment,
    )


class RuleBasedObserver:
    """Deterministic default Observer; Jev is an optional provider."""

    provider = "rule-based-observer"
    model_version = "market-state-v2"

    def judge(self, frame: MarketStateFrame) -> ContinuousJudgment:
        started = datetime.now(timezone.utc)
        assessment = frame.assessment or assess_market(
            _asset_from_frame(frame),
            data_quality_score=float(frame.quality_summary.get("score", "1.0")),
            source_alignment_seconds=_safe_int(frame.quality_summary.get("source_alignment_seconds")),
        )
        scores = _heuristic_scores(frame, assessment)
        conflicts = _conflict_roles(assessment)
        now = datetime.now(timezone.utc)
        return ContinuousJudgment(
            frame_id=frame.frame_id,
            asset=frame.asset,
            as_of=frame.as_of,
            selected_value=assessment.regime,
            probabilities=scores,
            confidence=max(scores.values()),
            score_kind="heuristic",
            supporting_roles=_available_roles(frame),
            contradicting_roles=conflicts,
            missing_roles=list(frame.missing_inputs),
            research_priority=_priority(assessment),
            invalidation_conditions=[REPORT_TEXT[assessment.regime][1]],
            provider=self.provider,
            model_version=self.model_version,
            latency_ms=max(0, int((now - started).total_seconds() * 1000)),
            created_at=_format_time(now),
        )


# Backward-compatible import for existing integrations and historical notebooks.
RuleBasedJevObserver = RuleBasedObserver


class RemoteJevObserver:
    """TypeSafe Jev System One API provider."""

    provider = "jev"
    model_version = "remote"

    def __init__(self, api_url: str, api_key: str, model: str, timeout: float = 20.0):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "RemoteJevObserver":
        url = os.getenv("TELLAGENT_JEV_API_URL", "https://api.typesafe.ai/v1/systemone")
        key = os.getenv("TELLAGENT_JEV_API_KEY")
        model = os.getenv("TELLAGENT_JEV_MODEL", "jev-latest")
        if not key:
            raise ValueError("Jev requires TELLAGENT_JEV_API_KEY.")
        return cls(url, key, model)

    def judge(self, frame: MarketStateFrame, client: httpx.Client | None = None) -> ContinuousJudgment:
        started = datetime.now(timezone.utc)
        payload = {
            "model": self.model,
            "state": frame.model_dump(),
            "questions": {
                "market_state": {
                    "type": "choice",
                    "instructions": "Which market regime best matches this BTC or ETH frame?",
                    "criteria": REGIME_CRITERIA,
                },
                "research_priority": {
                    "type": "choice",
                    "instructions": "How urgently should a stronger market analyst review this frame?",
                    "criteria": {
                        "silent": "No meaningful activity or research value.",
                        "watch": "Monitor for confirmation but do not escalate yet.",
                        "significant": "Meaningful activity or conflict merits analysis now.",
                        "urgent": "Extreme or sharply conflicting evidence requires immediate analysis.",
                    },
                },
                "signal_conflict": {
                    "type": "choice",
                    "instructions": "Which contradictory evidence role is most important?",
                    "criteria": {
                        "aligned": "Price, spot, and leverage evidence is broadly aligned.",
                        "spot_confirmation": "Spot activity contradicts the leverage interpretation.",
                        "funding_extreme": "Funding crowding contradicts the primary interpretation.",
                        "mixed": "Multiple evidence roles materially conflict.",
                    },
                },
            },
        }
        owns_client = client is None
        client = client or httpx.Client(timeout=self.timeout)
        try:
            response = client.post(
                self.api_url,
                headers={"Authorization": "Bearer " + self.api_key},
                json=payload,
            )
            response.raise_for_status()
            answers = response.json()["answers"]
            market_answer = answers["market_state"]
            selected_value = market_answer["choice"]
            probabilities = market_answer["probabilities"]
            conflict = answers["signal_conflict"]["choice"]
            now = datetime.now(timezone.utc)
            judgment = ContinuousJudgment(
                frame_id=frame.frame_id,
                asset=frame.asset,
                as_of=frame.as_of,
                provider=self.provider,
                model_version=self.model,
                latency_ms=max(0, int((now - started).total_seconds() * 1000)),
                created_at=_format_time(now),
                selected_value=selected_value,
                probabilities=probabilities,
                confidence=market_answer["confidence"],
                score_kind="probability",
                supporting_roles=_available_roles(frame),
                contradicting_roles=_conflict_answer_roles(conflict),
                missing_roles=list(frame.missing_inputs),
                research_priority=answers["research_priority"]["choice"],
                invalidation_conditions=[REPORT_TEXT[selected_value][1]],
            )
            _validate_judgment_probabilities(judgment)
            return judgment
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Remote Jev failed: {}".format(exc)) from exc
        finally:
            if owns_client:
                client.close()


REGIME_CRITERIA = {
    "quiet": "Price, spot, and leverage activity is quiet.",
    "spot_confirmed_up": "Price rises with strong spot confirmation and stable leverage.",
    "spot_confirmed_down": "Price falls with strong spot confirmation and stable leverage.",
    "leverage_expansion_up": "Price rises with expanding leverage and weak spot confirmation.",
    "leverage_expansion_down": "Price falls with expanding leverage and weak spot confirmation.",
    "position_unwind_up": "Price rises while open interest contracts.",
    "position_unwind_down": "Price falls while open interest contracts.",
    "broad_participation_up": "Price rises with both strong spot activity and leverage expansion.",
    "broad_participation_down": "Price falls with both strong spot activity and leverage expansion.",
    "unconfirmed_move_up": "Price rises, but neither spot activity nor leverage confirms the move.",
    "unconfirmed_move_down": "Price falls, but neither spot activity nor leverage confirms the move.",
    "conflicting": "Complete evidence is active but does not support one coherent driver.",
    "insufficient_data": "Critical data is missing, so no regime is justified.",
}


def _heuristic_scores(frame: MarketStateFrame, assessment) -> Dict[str, float]:
    if assessment.regime_scores:
        scores = dict(assessment.regime_scores)
        total = sum(scores.values())
        if total > 0:
            normalized = {key: round(value / total, 4) for key, value in scores.items()}
            selected = assessment.regime
            normalized[selected] = round(normalized[selected] + (1.0 - sum(normalized.values())), 4)
            return normalized
    scores = {regime: 0.0 for regime in REGIMES}
    selected = assessment.regime
    price = abs(frame.price_state.get("change_1h") or 0.0)
    oi, oi_threshold = _frame_oi_signal(frame)
    volume = max(frame.spot_state.get("volume_change_1h") or 0.0, 0.0)
    price_threshold = frame.strategy_thresholds.get("price_change_1h", 0.02)
    volume_threshold = frame.strategy_thresholds.get("spot_volume_change_1h", 0.05)
    strength = 0.45
    strength += 0.1 * min(price / max(price_threshold, 1e-9), 2) / 2
    if oi is not None:
        strength += 0.1 * min(abs(oi) / max(oi_threshold, 1e-9), 2) / 2
    strength += 0.1 * min(volume / max(volume_threshold, 1e-9), 2) / 2
    if selected == "quiet":
        strength = 0.75
    elif selected == "insufficient_data":
        strength = 0.65
    elif selected == "conflicting":
        strength = max(strength, 0.65)
    selected_score = round(min(strength, 0.9), 4)
    remainder = (1 - selected_score) / (len(REGIMES) - 1)
    for regime in REGIMES:
        scores[regime] = selected_score if regime == selected else round(remainder, 4)
    correction = round(1 - sum(scores.values()), 4)
    scores[selected] = round(scores[selected] + correction, 4)
    return scores


def _asset_from_frame(frame: MarketStateFrame) -> AssetSnapshot:
    return AssetSnapshot(
        symbol=frame.asset,
        price_change_1h=frame.price_state.get("change_1h"),
        price_change_6h=frame.price_state.get("change_6h"),
        realized_volatility_6h=frame.spot_state.get("realized_volatility_6h"),
        spot_volume_change_1h=frame.spot_state.get("volume_change_1h"),
        spot_volume_ratio_6h=frame.spot_state.get("volume_ratio_6h"),
        funding_rate=frame.leverage_state.get("funding_rate"),
        open_interest=frame.leverage_state.get("open_interest"),
        open_interest_change_interval=frame.leverage_state.get("open_interest_change_interval"),
        open_interest_change_1h=frame.leverage_state.get("open_interest_change_1h"),
        strategy_thresholds=frame.strategy_thresholds,
    )


def _safe_int(value: str | None) -> int | None:
    if value in {None, "unknown"}:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _frame_oi_signal(frame: MarketStateFrame) -> tuple[float | None, float]:
    one_hour = frame.leverage_state.get("open_interest_change_1h")
    if one_hour is not None:
        return one_hour, 0.08
    return (
        frame.leverage_state.get("open_interest_change_interval"),
        frame.strategy_thresholds.get("oi_interval", 0.015),
    )


def _priority(assessment) -> str:
    if assessment.regime == "quiet":
        return "silent"
    if assessment.regime == "insufficient_data":
        return "watch" if assessment.price_strength == "shock" else "silent"
    if assessment.regime == "conflicting":
        return "significant" if assessment.price_strength == "shock" else "watch"
    if assessment.regime == "leverage_expansion_down":
        return "significant"
    if assessment.regime.startswith("leverage_expansion"):
        return "significant" if (
            "spot_leverage_divergence" in assessment.risk_flags
            or assessment.funding_state != "neutral"
        ) else "watch"
    if assessment.regime.startswith("position_unwind"):
        return "significant" if assessment.price_strength == "shock" else "watch"
    if assessment.regime == "broad_participation_down":
        return "significant"
    if assessment.regime.startswith("unconfirmed_move"):
        return "significant" if assessment.price_strength == "shock" else "watch"
    return "watch"


def _conflict_roles(assessment) -> List[str]:
    roles = []
    if "spot_leverage_divergence" in assessment.risk_flags:
        roles.append("spot_confirmation")
    if assessment.funding_state in {"long_crowded", "short_crowded"}:
        roles.append("funding_extreme")
    if assessment.alignment == "conflicting":
        roles.append("signal_conflict")
    return roles


def _available_roles(frame: MarketStateFrame) -> List[str]:
    roles = ["price_state"]
    if frame.spot_state.get("volume_change_1h") is not None:
        roles.append("spot_state")
    if any(value is not None for value in frame.leverage_state.values()):
        roles.append("leverage_state")
    return roles


def _conflict_answer_roles(value: str) -> List[str]:
    return {
        "aligned": [],
        "spot_confirmation": ["spot_confirmation"],
        "funding_extreme": ["funding_extreme"],
        "mixed": ["spot_confirmation", "funding_extreme", "signal_conflict"],
    }[value]


def _validate_judgment_probabilities(judgment: ContinuousJudgment) -> None:
    if set(judgment.probabilities) != set(REGIMES):
        raise ValueError("Jev market_state probabilities must contain exactly the v2 regimes")
    if any(value < 0 or value > 1 for value in judgment.probabilities.values()):
        raise ValueError("Jev probabilities must be between 0 and 1")
    total = sum(judgment.probabilities.values())
    if abs(total - 1.0) > 0.01:
        raise ValueError("Jev probabilities must sum to 1.0, got {:.4f}".format(total))
    if judgment.selected_value not in judgment.probabilities:
        raise ValueError("Jev selected_value is absent from probabilities")


def _format_time(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")
