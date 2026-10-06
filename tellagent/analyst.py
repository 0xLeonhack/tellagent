import json
import os
from dataclasses import dataclass
from typing import Optional

import httpx

from .metrics import analysis_fields, analyze_asset
from .schemas import AssetSnapshot, MarketReport, MarketSnapshot


def generate_demo_report(snapshot: MarketSnapshot, asset: AssetSnapshot) -> MarketReport:
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


@dataclass(frozen=True)
class RemoteAnalystConfig:
    api_url: str
    api_key: str
    model: str
    timeout: float = 20.0

    @classmethod
    def from_env(cls) -> "RemoteAnalystConfig":
        api_url = os.getenv("TELLAGENT_MODEL_API_URL")
        api_key = os.getenv("TELLAGENT_MODEL_API_KEY")
        model = os.getenv("TELLAGENT_MODEL_NAME", "market-analyst")
        if not api_url or not api_key:
            raise ValueError(
                "Remote analyst requires TELLAGENT_MODEL_API_URL and "
                "TELLAGENT_MODEL_API_KEY."
            )
        return cls(api_url=api_url, api_key=api_key, model=model)


def generate_remote_report(
    snapshot: MarketSnapshot,
    asset: AssetSnapshot,
    config: RemoteAnalystConfig,
    client: Optional[httpx.Client] = None,
) -> MarketReport:
    """Ask an OpenAI-compatible endpoint to organize precomputed evidence."""
    analysis = analyze_asset(asset)
    facts = {
        "asset": asset.model_dump(),
        "supporting_evidence": analysis.evidence.supporting,
        "contradicting_evidence": analysis.evidence.contradicting,
        "missing_evidence": analysis.evidence.missing,
    }
    payload = {
        "model": config.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a constrained crypto market analyst. Return JSON only. "
                    "Use only the supplied facts. Do not invent news, calculate new "
                    "metrics, or give trading instructions. The JSON must contain: "
                    "headline, state, confidence, supporting_evidence, "
                    "contradicting_evidence, missing_evidence, "
                    "invalidation_condition."
                ),
            },
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ],
    }
    owns_client = client is None
    client = client or httpx.Client(timeout=config.timeout)
    try:
        try:
            response = client.post(
                config.api_url,
                headers={"Authorization": "Bearer " + config.api_key},
                json=payload,
            )
            response.raise_for_status()
            raw = response.json()
            content = _extract_model_content(raw)
            model_fields = json.loads(content) if isinstance(content, str) else content
            if not isinstance(model_fields, dict):
                raise ValueError("Model response must be a JSON object.")
            return MarketReport(
                asset=asset.symbol,
                metrics=asset,
                data_time=snapshot.as_of,
                sources=snapshot.sources,
                **model_fields,
            )
        except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("Remote analyst failed: {}".format(exc)) from exc
    finally:
        if owns_client:
            client.close()


def _extract_model_content(payload: object):
    if isinstance(payload, dict) and "headline" in payload:
        return payload
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Model response has no chat completion content.") from exc
