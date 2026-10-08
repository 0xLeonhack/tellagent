from datetime import datetime, timezone
from hashlib import sha256
from typing import Dict, List, Tuple

from .metrics import analyze_asset
from .schemas import AssetSnapshot, ContinuousJudgment, MarketStateFrame, MarketSnapshot


QUESTION_SET_VERSION = "demo.observer.v1"


def build_state_frame(snapshot: MarketSnapshot, asset: AssetSnapshot) -> MarketStateFrame:
    """Convert a snapshot into the compact state passed to an Observer."""
    analysis = analyze_asset(asset)
    frame_id = sha256(
        "{}:{}:{}".format(asset.symbol, snapshot.as_of, asset.model_dump_json()).encode()
    ).hexdigest()[:16]
    return MarketStateFrame(
        frame_id=frame_id,
        asset=asset.symbol,
        as_of=snapshot.as_of,
        price_state={"change_1h": asset.price_change_1h, "change_6h": asset.price_change_6h},
        spot_state={"volume_change_1h": asset.spot_volume_change_1h},
        leverage_state={"funding_rate": asset.funding_rate, "open_interest_change_1h": asset.open_interest_change_1h},
        anomalies=list(analysis.evidence.supporting),
        missing_inputs=list(analysis.evidence.missing),
        quality_summary={
            "source_count": str(len(snapshot.sources)),
            "missing_count": str(len(analysis.evidence.missing)),
            "status": "degraded" if analysis.evidence.missing else "ok",
        },
    )


class RuleBasedJevObserver:
    """Local Jev-compatible Observer for the demo.

    It emits the structured judgment contract planned for Jev, using
    deterministic rules until an external Jev provider is available.
    """

    provider = "rule-based-jev"
    model_version = "rules-v1"

    def judge(self, frame: MarketStateFrame) -> ContinuousJudgment:
        started = datetime.now(timezone.utc)
        price = frame.price_state.get("change_1h")
        volume = frame.spot_state.get("volume_change_1h")
        oi = frame.leverage_state.get("open_interest_change_1h")
        funding = frame.leverage_state.get("funding_rate")
        state, probabilities = _state_probabilities(price, volume, oi)
        conflicts = _conflict_roles(state, volume, oi, funding)
        priority = _priority(state, frame, conflicts)
        supporting = ["price_state", "spot_state", "leverage_state"] if state != "uncertain" else []
        now = datetime.now(timezone.utc)
        return ContinuousJudgment(
            frame_id=frame.frame_id,
            asset=frame.asset,
            as_of=frame.as_of,
            selected_value=state,
            probabilities=probabilities,
            confidence=round(max(probabilities.values()), 2),
            supporting_roles=supporting,
            contradicting_roles=conflicts,
            missing_roles=list(frame.missing_inputs),
            research_priority=priority,
            invalidation_conditions=_invalidation_conditions(state),
            provider=self.provider,
            model_version=self.model_version,
            latency_ms=max(0, int((now - started).total_seconds() * 1000)),
            created_at=now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        )


def _state_probabilities(price: float | None, volume: float | None, oi: float | None) -> Tuple[str, Dict[str, float]]:
    leverage = price is not None and price > 0.02 and oi is not None and oi > 0.08 and (volume is None or volume < oi * 0.75)
    spot = price is not None and price > 0.02 and volume is not None and volume > 0.05 and (oi is None or oi <= 0.12)
    deleveraging = price is not None and price < -0.02 and oi is not None and oi < -0.08
    if leverage:
        return "leverage_led", {"leverage_led": 0.82, "spot_confirmed": 0.08, "deleveraging": 0.02, "uncertain": 0.08}
    if spot:
        return "spot_confirmed", {"leverage_led": 0.08, "spot_confirmed": 0.78, "deleveraging": 0.02, "uncertain": 0.12}
    if deleveraging:
        return "deleveraging", {"leverage_led": 0.03, "spot_confirmed": 0.04, "deleveraging": 0.82, "uncertain": 0.11}
    return "uncertain", {"leverage_led": 0.12, "spot_confirmed": 0.18, "deleveraging": 0.08, "uncertain": 0.62}


def _conflict_roles(state: str, volume: float | None, oi: float | None, funding: float | None) -> List[str]:
    roles: List[str] = []
    if state == "leverage_led" and volume is not None and volume > 0:
        roles.append("spot_confirmation")
    if state == "spot_confirmed" and funding is not None and funding > 0.0002:
        roles.append("funding_extreme")
    if state == "spot_confirmed" and oi is not None and oi > 0.08:
        roles.append("leverage_expansion")
    return roles


def _priority(state: str, frame: MarketStateFrame, conflicts: List[str]) -> str:
    if state == "uncertain":
        return "watch" if frame.missing_inputs else "silent"
    if conflicts and len(frame.missing_inputs) <= 1:
        return "significant"
    return "watch"


def _invalidation_conditions(state: str) -> List[str]:
    return {
        "leverage_led": ["spot volume expands while open interest falls"],
        "spot_confirmed": ["spot volume falls while open interest expands"],
        "deleveraging": ["open interest recovers and price reverses higher"],
        "uncertain": ["obtain a complete price, spot, and derivatives frame"],
    }[state]
