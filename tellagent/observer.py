import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from typing import Dict, List, Optional, Protocol

import httpx

from .assessment import (
    assess_market,
    assess_snapshot_quality,
    assessment_evidence,
    source_max_age_seconds,
)
from .metrics import REPORT_TEXT, analyze_asset
from .schemas import AssetSnapshot, ContinuousJudgment, FeatureBaseline, MarketStateFrame, MarketSnapshot
from .scoring import REGIMES, score_confidence


class JudgmentProvider(Protocol):
    provider: str
    model_version: str

    def judge(self, frame: MarketStateFrame) -> ContinuousJudgment: ...


FRAME_FINGERPRINT_VERSION = "v2"
FRAME_FINGERPRINT_FIELDS = (
    "symbol",
    "spot_price",
    "price_change_1h",
    "price_change_6h",
    "realized_volatility_6h",
    "spot_volume_change_1h",
    "spot_volume_ratio_6h",
    "funding_rate",
    "open_interest",
    "open_interest_change_interval",
    "open_interest_interval_seconds",
    "open_interest_change_1h",
    "strategy_thresholds",
)


def frame_fingerprint(asset: AssetSnapshot, as_of: str) -> str:
    """Stable content hash for a frame's evidence.

    Only an explicit field list is hashed. Adding unrelated schema fields
    later must not silently invalidate every historic frame id.
    """
    payload = {
        "version": FRAME_FINGERPRINT_VERSION,
        "as_of": as_of,
        "asset": {name: getattr(asset, name) for name in FRAME_FINGERPRINT_FIELDS},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(canonical.encode()).hexdigest()[:16]


LEGACY_FINGERPRINT_FIELDS = {
    "symbol",
    "spot_price",
    "price_change_1h",
    "price_change_6h",
    "realized_volatility_6h",
    "spot_volume_change_1h",
    "spot_volume_ratio_6h",
    "funding_rate",
    "open_interest",
    "open_interest_change_interval",
    "open_interest_change_1h",
    "strategy_thresholds",
}


def legacy_frame_fingerprint(
    asset: AssetSnapshot,
    as_of: str,
    fields: Optional[set[str]] = None,
) -> str:
    """The pre-v2 id formula, kept so old ledger frames stay auditable.

    The original formula hashed ``asset.model_dump_json()`` with whatever
    fields the schema had at that time. Fields added later (for example
    ``realized_volatility_6h``) must not be included when recomputing an old
    id, so callers that parsed an old record pass the exact field set that was
    stored with it (``asset.model_fields_set``).
    """
    include = LEGACY_FINGERPRINT_FIELDS if fields is None else set(fields)
    legacy_json = asset.model_dump_json(include=include)
    return sha256(
        "{}:{}:{}".format(asset.symbol, as_of, legacy_json).encode()
    ).hexdigest()[:16]


def build_state_frame(
    snapshot: MarketSnapshot,
    asset: AssetSnapshot,
    baseline_state: Dict[str, FeatureBaseline] | None = None,
) -> MarketStateFrame:
    quality_score, alignment_seconds = assess_snapshot_quality(snapshot, asset)
    max_age_seconds = source_max_age_seconds(snapshot, asset)
    analysis = analyze_asset(asset, quality_score, alignment_seconds)
    frame_id = frame_fingerprint(asset, snapshot.as_of)
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
            "open_interest_interval_seconds": asset.open_interest_interval_seconds,
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
            "source_max_age_seconds": str(max_age_seconds) if max_age_seconds is not None else "unknown",
            "data_errors": "; ".join(
                "{}: {}".format(symbol, message)
                for symbol, message in sorted(snapshot.data_errors.items())
            ) or "none",
        },
        baseline_state=baseline_state or {},
        strategy_thresholds=asset.strategy_thresholds,
        assessment=analysis.assessment,
    )


class RuleBasedObserver:
    """Deterministic default Observer; Jev is an optional provider."""

    provider = "rule-based-observer"
    model_version = "market-state-v4"

    def judge(self, frame: MarketStateFrame) -> ContinuousJudgment:
        started = datetime.now(timezone.utc)
        asset = _asset_from_frame(frame)
        assessment = frame.assessment or assess_market(
            asset,
            data_quality_score=float(frame.quality_summary.get("score", "1.0")),
            source_alignment_seconds=_safe_int(frame.quality_summary.get("source_alignment_seconds")),
        )
        scores = _heuristic_scores(assessment)
        evidence = assessment_evidence(asset, assessment)
        conflicts = _conflict_roles(assessment)
        confidence = score_confidence(scores, evidence)
        now = datetime.now(timezone.utc)
        return ContinuousJudgment(
            frame_id=frame.frame_id,
            asset=frame.asset,
            as_of=frame.as_of,
            selected_value=assessment.regime,
            probabilities=scores,
            confidence=confidence,
            score_kind="heuristic",
            supporting_roles=_available_roles(frame),
            contradicting_roles=conflicts,
            missing_roles=list(frame.missing_inputs),
            research_priority=_priority(assessment, evidence),
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


def _heuristic_scores(assessment) -> Dict[str, float]:
    """Return the evidence distribution produced with the assessment.

    ``assess_market`` always fills ``regime_scores`` with a softmax over all
    regimes. The normalisation below only guards rows written by older
    versions, which could contain an unnormalised or one-hot vector.
    """
    scores = {regime: float(assessment.regime_scores.get(regime, 0.0)) for regime in REGIMES}
    total = sum(scores.values())
    if total <= 0:
        scores[assessment.regime] = 1.0
        return scores
    normalized = {regime: round(value / total, 6) for regime, value in scores.items()}
    drift = round(1.0 - sum(normalized.values()), 6)
    if drift:
        normalized[assessment.regime] = round(normalized[assessment.regime] + drift, 6)
    return normalized


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
        open_interest_interval_seconds=frame.leverage_state.get("open_interest_interval_seconds"),
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


def _priority(assessment, evidence) -> str:
    """Map a regime and its risk flags to research urgency.

    The mapping stays deterministic and coarse on purpose: the Gate adds
    confirmation and materiality, so priority itself should not be noisy.
    """
    regime = assessment.regime
    shock = assessment.price_strength == "shock"
    # "Urgent" is reserved for moves at least 2.5x the calibrated threshold;
    # otherwise almost every shock would outrank the truly extreme frames.
    extreme = abs(evidence.price_z) >= 2.5
    crowded = assessment.funding_state in {"long_crowded", "short_crowded"}
    divergence = "spot_leverage_divergence" in assessment.risk_flags
    if regime == "quiet":
        return "silent"
    if regime == "insufficient_data":
        return "watch" if shock else "silent"
    if regime == "conflicting":
        return "significant" if shock or crowded else "watch"
    if regime == "leverage_expansion_down":
        return "urgent" if extreme and crowded else "significant"
    if regime.startswith("leverage_expansion"):
        return "significant" if divergence or crowded or shock else "watch"
    if regime.startswith("position_unwind"):
        return "significant" if shock or crowded else "watch"
    if regime == "broad_participation_down":
        return "urgent" if extreme and crowded else "significant"
    if regime.startswith("broad_participation"):
        return "significant" if shock else "watch"
    if regime.startswith("unconfirmed_move"):
        return "significant" if shock or crowded else "watch"
    if regime.startswith("spot_confirmed"):
        return "significant" if shock else "watch"
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
