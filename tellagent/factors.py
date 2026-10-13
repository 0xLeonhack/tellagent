from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .schemas import (
    ContinuousJudgment,
    FactorHypothesis,
    FactorResult,
    MarketReport,
    ResearchGuidance,
)


FACTOR_DEFINITIONS = {
    "leverage_dominance": {
        "inputs": ["price_change_1h", "funding_rate", "open_interest_change_interval", "spot_volume_change_1h"],
        "formula": "zscore(oi_change) + zscore(funding) - zscore(spot_volume_change)",
        "direction": "negative_after_extreme",
        "horizon": "1h_to_6h",
    },
    "spot_derivatives_divergence": {
        "inputs": ["spot_volume_change_1h", "open_interest_change_interval", "funding_rate"],
        "formula": "zscore(derivatives_growth) - zscore(spot_volume_change)",
        "direction": "reversal_risk_rises_with_divergence",
        "horizon": "1h_to_6h",
    },
    "spot_confirmation": {
        "inputs": ["price_change_1h", "spot_volume_change_1h", "open_interest_change_interval"],
        "formula": "zscore(spot_volume_change) - abs(zscore(oi_change))",
        "direction": "positive_when_spot_confirms",
        "horizon": "1h_to_6h",
    },
    "unlevered_price_move": {
        "inputs": ["price_change_1h", "spot_volume_change_1h", "funding_rate"],
        "formula": "zscore(price_change) + zscore(spot_volume_change) - abs(zscore(funding))",
        "direction": "positive_when_leverage_is_muted",
        "horizon": "1h_to_6h",
    },
    "deleveraging_pressure": {
        "inputs": ["price_change_1h", "open_interest_change_interval", "funding_rate"],
        "formula": "-zscore(price_change) - zscore(oi_change)",
        "direction": "risk_rises_with_joint_price_and_oi_decline",
        "horizon": "1h_to_6h",
    },
    "forced_position_reduction": {
        "inputs": ["open_interest_change_interval", "spot_volume_change_1h"],
        "formula": "-zscore(oi_change) - zscore(spot_volume_change)",
        "direction": "positive_when_oi_unwinds_without_spot_confirmation",
        "horizon": "1h_to_6h",
    },
}


class JsonlFactorStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def append_hypothesis(self, hypothesis: FactorHypothesis) -> None:
        path = self.root / "factor_hypotheses.jsonl"
        existing = {item.hypothesis_id for item in self.hypotheses()}
        if hypothesis.hypothesis_id not in existing:
            self._append(path, hypothesis.model_dump_json())
            self.write_worldquant_drafts()

    def append_result(self, result: FactorResult) -> None:
        self._append(self.root / "factor_results.jsonl", result.model_dump_json())

    def hypotheses(self) -> List[FactorHypothesis]:
        path = self.root / "factor_hypotheses.jsonl"
        if not path.exists():
            return []
        return [FactorHypothesis.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def write_worldquant_drafts(self) -> Path:
        path = self.root / "worldquant_drafts.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_worldquant_drafts(self.hypotheses()), encoding="utf-8")
        return path

    @staticmethod
    def _append(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")


def build_factor_hypotheses(
    judgment: ContinuousJudgment,
    guidance: ResearchGuidance,
    report: Optional[MarketReport],
) -> List[FactorHypothesis]:
    rationale = report.headline if report else "{} market state".format(judgment.selected_value)
    invalidation = guidance.invalidation_conditions[0] if guidance.invalidation_conditions else "state changes"
    hypotheses = []
    for name in guidance.factor_candidates:
        definition = FACTOR_DEFINITIONS.get(name)
        if definition is None:
            continue
        hypotheses.append(FactorHypothesis(
            hypothesis_id="{}:{}:{}".format(judgment.asset, judgment.frame_id, name),
            created_at=_now(),
            source_frame_id=judgment.frame_id,
            asset=judgment.asset,
            name=name,
            regime=judgment.selected_value,
            inputs=definition["inputs"],
            formula_draft=definition["formula"],
            expected_direction=definition["direction"],
            horizon=definition["horizon"],
            rationale=rationale,
            invalidation_condition=invalidation,
            test_plan="Evaluate IC, rank IC, grouped returns, turnover, costs, and out-of-sample stability by regime.",
        ))
    return hypotheses


def render_worldquant_drafts(hypotheses: List[FactorHypothesis]) -> str:
    lines = [
        "# WorldQuant Expression Drafts",
        "",
        "> These are research drafts, not directly submittable alphas. Map every placeholder to an available BRAIN field and validate operators, delay, universe, neutralization, turnover, correlation, and out-of-sample performance.",
        "",
    ]
    for item in hypotheses:
        lines.extend([
            "## {} · {}".format(item.asset, item.name),
            "",
            "- Hypothesis ID: `{}`".format(item.hypothesis_id),
            "- Regime: `{}`".format(item.regime),
            "- Horizon: `{}`".format(item.horizon),
            "- Expected direction: `{}`".format(item.expected_direction),
            "- Invalidation: {}".format(item.invalidation_condition),
            "",
            "Expression concept:",
            "",
            "```text",
            item.formula_draft,
            "```",
            "",
            "Required field mapping:",
            "",
        ])
        lines.extend("- `{}` → `<BRAIN_FIELD>`".format(field) for field in item.inputs)
        lines.extend(["", "Validation: {}".format(item.test_plan), ""])
    return "\n".join(lines).rstrip() + "\n"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
