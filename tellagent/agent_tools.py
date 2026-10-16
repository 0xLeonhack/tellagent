from pathlib import Path
from typing import Any, Optional

from .evidence import build_evidence_catalog
from .ledger import JsonlLedger
from .memory import JsonlMemory
from .schemas import ContinuousJudgment, EvidenceBundle, MarketStateFrame
from .tools import ToolRegistry


def build_research_tool_registry(
    root: Path,
    frame: MarketStateFrame,
    judgment: ContinuousJudgment,
    evidence: Optional[EvidenceBundle] = None,
) -> ToolRegistry:
    """Build a read-only registry scoped to the current Agent frame."""
    root = Path(root)
    ledger = JsonlLedger(root)
    memory = JsonlMemory(root / "memory.jsonl")
    registry = ToolRegistry()

    registry.register(
        "read_recent_judgments",
        "Read recent judgments for the current asset.",
        lambda args: _recent_judgments(ledger, frame.asset, args),
    )
    registry.register(
        "read_similar_memory",
        "Read related research memory for the current asset and regime.",
        lambda args: _similar_memory(memory, frame.asset, judgment.selected_value, args),
    )
    registry.register(
        "read_outcome_calibration",
        "Read deterministic outcome calibration summaries.",
        lambda args: _calibration(root),
    )
    registry.register(
        "read_evidence_catalog",
        "Read the frozen evidence catalog for the current frame.",
        lambda args: _evidence_catalog(frame.asset, evidence),
    )
    return registry


def _recent_judgments(ledger: JsonlLedger, asset: str, args: dict[str, Any]) -> dict[str, Any]:
    limit = int(args.get("limit", 12))
    if limit < 1 or limit > 50:
        raise ValueError("limit must be between 1 and 50")
    judgments = ledger.judgments(asset)[-limit:]
    return {"asset": asset, "count": len(judgments), "judgments": [item.model_dump() for item in judgments]}


def _similar_memory(memory: JsonlMemory, asset: str, state: str, args: dict[str, Any]) -> dict[str, Any]:
    limit = int(args.get("limit", 5))
    if limit < 1 or limit > 20:
        raise ValueError("limit must be between 1 and 20")
    records = memory.related(asset, state=state, tags=args.get("tags", []), limit=limit)
    return {"asset": asset, "state": state, "count": len(records), "records": [item.model_dump() for item in records]}


def _calibration(root: Path) -> dict[str, Any]:
    path = root / "calibration_report.json"
    if not path.exists():
        return {"available": False, "calibration": []}
    import json
    return {"available": True, "calibration": json.loads(path.read_text(encoding="utf-8"))}


def _evidence_catalog(asset: str, evidence: Optional[EvidenceBundle]) -> dict[str, Any]:
    catalog = build_evidence_catalog(asset, evidence) if evidence else []
    return {"asset": asset, "count": len(catalog), "evidence": [item.model_dump() for item in catalog]}
