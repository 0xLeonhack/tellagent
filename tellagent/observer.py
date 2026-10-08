import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from typing import Dict, List, Tuple

import httpx

from .metrics import analyze_asset
from .schemas import AssetSnapshot, ContinuousJudgment, MarketStateFrame, MarketSnapshot


QUESTION_SET_VERSION = "tellagent.observer.v1"


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
            "status": "degraded" if analysis.evidence.missing else "ok",
        },
    )


class RuleBasedJevObserver:
    """Local Jev-compatible Observer.

    It emits the structured judgment contract planned for Jev, using
    deterministic rules until an external Jev provider is available.
    """

    provider = "rule-based-jev"
    model_version = "rules-v1"

    def judge(self, frame: MarketStateFrame) -> ContinuousJudgment:
        started = datetime.now(timezone.utc)
        price = frame.price_state.get("change_1h")
        volume = frame.spot_state.get("volume_change_1h")
        oi_1h = frame.leverage_state.get("open_interest_change_1h")
        oi_interval = frame.leverage_state.get("open_interest_change_interval")
        funding = frame.leverage_state.get("funding_rate")
        state, probabilities = _state_probabilities(price, volume, oi_1h, oi_interval)
        conflicts = _conflict_roles(state, volume, oi_1h, funding)
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


class RemoteJevObserver:
    """Optional OpenAI-compatible Observer Provider.

    The endpoint is configured explicitly because Jev's provider API is not
    assumed to be identical to a generic chat API.
    """

    provider = "jev"
    model_version = "remote"

    def __init__(self, api_url: str, api_key: str, model: str, timeout: float = 20.0):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "RemoteJevObserver":
        url = os.getenv("TELLAGENT_JEV_API_URL")
        key = os.getenv("TELLAGENT_JEV_API_KEY")
        model = os.getenv("TELLAGENT_JEV_MODEL", "jev-observer")
        if not url or not key:
            raise ValueError("Jev requires TELLAGENT_JEV_API_URL and TELLAGENT_JEV_API_KEY.")
        return cls(url, key, model)

    def judge(self, frame: MarketStateFrame, client: httpx.Client | None = None) -> ContinuousJudgment:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are Jev, a constrained market Observer. Return JSON only. "
                        "Do not fetch data or invent evidence. Return probabilities for "
                        "leverage_led, spot_confirmed, deleveraging, uncertain; they must "
                        "sum to 1. Include selected_value, confidence, supporting_roles, "
                        "contradicting_roles, missing_roles, research_priority, "
                        "invalidation_conditions."
                    ),
                },
                {"role": "user", "content": frame.model_dump_json()},
            ],
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
            raw = response.json()
            content = raw["choices"][0]["message"]["content"]
            fields = json.loads(content) if isinstance(content, str) else content
            judgment = ContinuousJudgment(
                frame_id=frame.frame_id,
                asset=frame.asset,
                as_of=frame.as_of,
                provider=self.provider,
                model_version=self.model,
                latency_ms=0,
                created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                **fields,
            )
            _validate_judgment_probabilities(judgment)
            return judgment
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Remote Jev failed: {}".format(exc)) from exc
        finally:
            if owns_client:
                client.close()


def _validate_judgment_probabilities(judgment: ContinuousJudgment) -> None:
    total = sum(judgment.probabilities.values())
    if abs(total - 1.0) > 0.01:
        raise ValueError("Jev probabilities must sum to 1.0, got {:.4f}".format(total))
    if judgment.selected_value not in judgment.probabilities:
        raise ValueError("Jev selected_value is absent from probabilities")


def _state_probabilities(
    price: float | None,
    volume: float | None,
    oi_1h: float | None,
    oi_interval: float | None,
) -> Tuple[str, Dict[str, float]]:
    oi_signal = oi_1h if oi_1h is not None else oi_interval
    oi_threshold = 0.08 if oi_1h is not None else 0.015
    leverage = price is not None and price > 0.02 and oi_signal is not None and oi_signal > oi_threshold and (volume is None or volume < max(oi_signal * 0.75, 0.02))
    spot = price is not None and price > 0.02 and volume is not None and volume > 0.05 and (oi_signal is None or oi_signal <= oi_threshold)
    deleveraging = price is not None and price < -0.02 and oi_signal is not None and oi_signal < -oi_threshold
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
