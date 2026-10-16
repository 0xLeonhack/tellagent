from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .evidence import build_evidence_catalog
from .factors import FACTOR_DEFINITIONS, JsonlFactorStore
from .ledger import JsonlLedger
from .memory import JsonlMemory
from .review import OutcomeReviewer
from .schemas import (
    ContinuousJudgment,
    EvidenceBundle,
    FactorHypothesis,
    MarketStateFrame,
    ResearchGuidance,
)
from .tools import ToolRegistry


def build_research_tool_registry(
    root: Path,
    frame: MarketStateFrame,
    judgment: ContinuousJudgment,
    evidence: Optional[EvidenceBundle] = None,
    guidance: Optional[ResearchGuidance] = None,
    store: Optional[JsonlFactorStore] = None,
    as_of_cutoff: Optional[str] = None,
) -> ToolRegistry:
    """Build the statically registered tool surface scoped to the current Agent frame.

    Read-only tools expose project ledgers. The only writer is
    ``create_factor_hypothesis``, which appends a research hypothesis. No tool can
    trade, execute code, reach the network, or rewrite history.

    ``as_of_cutoff`` hides everything recorded after the frame under study, so a
    replayed frame sees exactly what was available at the time.
    """
    root = Path(root)
    ledger = JsonlLedger(root)
    memory = JsonlMemory(root / "memory.jsonl")
    reviewer = OutcomeReviewer(root)
    factor_store = store or JsonlFactorStore(root)

    registry = ToolRegistry()
    registry.register(
        "read_recent_judgments",
        "Read recent Observer judgments for the current asset.",
        lambda args: _recent_judgments(ledger, frame.asset, args, as_of_cutoff),
    )
    registry.register(
        "read_similar_memory",
        "Read related research memory for the current asset and regime.",
        lambda args: _similar_memory(
            memory, frame.asset, judgment.selected_value, args, as_of_cutoff
        ),
    )
    registry.register(
        "read_outcome_calibration",
        "Read deterministic outcome calibration summaries grouped by state and horizon.",
        lambda args: _calibration(root),
    )
    registry.register(
        "read_recent_outcomes",
        "Read deterministic outcome reviews for the current asset, optionally filtered by state.",
        lambda args: _recent_outcomes(
            reviewer, frame.asset, judgment.selected_value, args, as_of_cutoff
        ),
    )
    registry.register(
        "read_evidence_catalog",
        "Read the frozen evidence catalog for the current frame.",
        lambda args: _evidence_catalog(frame.asset, evidence),
    )
    registry.register(
        "create_factor_hypothesis",
        "Append one research factor hypothesis chosen from the predefined factor catalog.",
        lambda args: _create_factor_hypothesis(factor_store, judgment, guidance, args),
    )
    return registry


def _recent_judgments(
    ledger: JsonlLedger,
    asset: str,
    args: dict[str, Any],
    cutoff: Optional[str] = None,
) -> dict[str, Any]:
    limit = _limit(args, default=12, maximum=50)
    judgments = [item for item in ledger.judgments(asset) if _visible(item.as_of, cutoff)][-limit:]
    return {
        "asset": asset,
        "count": len(judgments),
        "selected_state": judgments[-1].selected_value if judgments else None,
        "judgments": [
            {
                "as_of": item.as_of,
                "state": item.selected_value,
                "state_probability": item.probabilities.get(item.selected_value),
                "confidence": item.confidence,
                "research_priority": item.research_priority,
                "provider": item.provider,
            }
            for item in judgments
        ],
    }


def _similar_memory(
    memory: JsonlMemory,
    asset: str,
    state: str,
    args: dict[str, Any],
    cutoff: Optional[str] = None,
) -> dict[str, Any]:
    limit = _limit(args, default=5, maximum=20)
    records = memory.related(asset, state=state, tags=args.get("tags", []), limit=20)
    records = [item for item in records if _visible(item.as_of, cutoff)][:limit]
    return {
        "asset": asset,
        "state": state,
        "count": len(records),
        "records": [
            {"as_of": item.as_of, "state": item.state, "summary": item.summary, "tags": item.tags}
            for item in records
        ],
    }


def _calibration(root: Path) -> dict[str, Any]:
    path = root / "calibration_report.json"
    if not path.exists():
        return {"available": False, "calibration": []}
    import json
    return {"available": True, "calibration": json.loads(path.read_text(encoding="utf-8"))}


def _recent_outcomes(
    reviewer: OutcomeReviewer,
    asset: str,
    state: str,
    args: dict[str, Any],
    cutoff: Optional[str] = None,
) -> dict[str, Any]:
    limit = _limit(args, default=10, maximum=50)
    reviews = [
        item for item in reviewer.reviews()
        if item.asset.upper() == asset.upper() and _visible(item.reviewed_at, cutoff)
    ]
    matching = [item for item in reviews if item.original_state == state]
    selected = (matching or reviews)[-limit:]
    return {
        "asset": asset,
        "state": state,
        "same_state_count": len(matching),
        "count": len(selected),
        "outcomes": [
            {
                "horizon": item.horizon,
                "reviewed_at": item.reviewed_at,
                "status": item.status,
                "realized_return": item.realized_return,
                "max_adverse_excursion": item.max_adverse_excursion,
                "invalidation_triggered": item.invalidation_triggered,
            }
            for item in selected
        ],
    }


def _evidence_catalog(asset: str, evidence: Optional[EvidenceBundle]) -> dict[str, Any]:
    catalog = build_evidence_catalog(asset, evidence) if evidence else []
    return {
        "asset": asset,
        "count": len(catalog),
        "evidence": [item.model_dump() for item in catalog],
    }


def _create_factor_hypothesis(
    store: JsonlFactorStore,
    judgment: ContinuousJudgment,
    guidance: Optional[ResearchGuidance],
    args: dict[str, Any],
) -> dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str) or name not in FACTOR_DEFINITIONS:
        raise ValueError("unknown factor name: {}".format(name))
    definition = FACTOR_DEFINITIONS[name]
    focus = list(guidance.focus) if guidance else []
    invalidation = (
        guidance.invalidation_conditions[0]
        if guidance and guidance.invalidation_conditions
        else "market state changes"
    )
    rationale = "Agent 在 {} 状态下选择该因子。研究重点：{}".format(
        judgment.selected_value,
        "、".join(focus) if focus else "等待更多确认数据",
    )
    note = args.get("note")
    if isinstance(note, str) and note.strip():
        rationale = "{} Agent 备注：{}".format(rationale, note.strip())
    hypothesis = FactorHypothesis(
        hypothesis_id="{}:{}:{}".format(judgment.asset, judgment.frame_id, name),
        created_at=_now(),
        source_frame_id=judgment.frame_id,
        asset=judgment.asset,
        name=name,
        regime=judgment.selected_value,
        inputs=list(definition["inputs"]),
        formula_draft=definition["formula"],
        expected_direction=definition["direction"],
        horizon=definition["horizon"],
        rationale=rationale,
        invalidation_condition=invalidation,
        test_plan=(
            "Evaluate IC, rank IC, grouped returns, turnover, costs, and "
            "out-of-sample stability by regime."
        ),
    )
    store.append_hypothesis(hypothesis)
    return {
        "hypothesis_id": hypothesis.hypothesis_id,
        "name": hypothesis.name,
        "regime": hypothesis.regime,
        "inputs": hypothesis.inputs,
        "formula_draft": hypothesis.formula_draft,
        "expected_direction": hypothesis.expected_direction,
        "horizon": hypothesis.horizon,
        "invalidation_condition": hypothesis.invalidation_condition,
        "created": True,
    }


def _visible(as_of: Optional[str], cutoff: Optional[str]) -> bool:
    """A record is visible unless it was created after the frame under study."""
    if cutoff is None or not as_of:
        return True
    return as_of <= cutoff


def _limit(args: dict[str, Any], default: int, maximum: int) -> int:
    try:
        limit = int(args.get("limit", default))
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if limit < 1 or limit > maximum:
        raise ValueError("limit must be between 1 and {}".format(maximum))
    return limit


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
