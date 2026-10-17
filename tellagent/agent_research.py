from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Optional

from .agent_loop import AgentLoop, DecisionProvider
from .agent_schemas import AGENT_ACTIONS, AgentRunSummary, AgentTrace, ToolResult
from .agent_tools import build_research_tool_registry
from .agent_trace import JsonlAgentTraceStore
from .evidence import build_evidence_catalog
from .factors import JsonlFactorStore
from .metrics import analyze_asset
from .schemas import (
    AssetSnapshot,
    ContinuousJudgment,
    FactorHypothesis,
    JudgmentTrend,
    MarketReport,
    MarketSnapshot,
    MarketStateFrame,
    ResearchGuidance,
)


MAX_MODEL_CALLS_PER_RUN = 3
ESCALATING_ACTIONS = frozenset({"finish", "generate_factor"})


@dataclass(frozen=True)
class AgentRequest:
    """Everything the Agent may look at for one asset frame."""

    snapshot: MarketSnapshot
    asset: AssetSnapshot
    frame: MarketStateFrame
    judgment: ContinuousJudgment
    trend: JudgmentTrend
    guidance: ResearchGuidance
    memory_context: str = ""
    gate_reason: str = ""
    replay_cutoff: Optional[str] = None
    """Set when replaying a recorded frame: tools hide everything newer than it."""


@dataclass(frozen=True)
class AgentRunOutcome:
    summary: AgentRunSummary
    report: Optional[MarketReport]
    factor_hypotheses: List[FactorHypothesis]
    escalated: bool = False


ReportBuilder = Callable[[AgentRequest], Optional[MarketReport]]


class AgentResearchRunner:
    """Run one bounded Agent loop per escalated frame and record a replayable trace.

    Code still owns facts, tool execution, the action allowlist, the step budget,
    and the model call budget. The Agent only chooses the next research action.
    """

    def __init__(
        self,
        root: Path,
        decide: DecisionProvider,
        provider_name: str,
        model_version: str,
        max_steps: int = 3,
        report_builder: Optional[ReportBuilder] = None,
        counts_model_calls: bool = True,
        report_counts_model_calls: bool = False,
        store: Optional[JsonlFactorStore] = None,
        trace_store: Optional[JsonlAgentTraceStore] = None,
    ):
        if max_steps < 1 or max_steps > 10:
            raise ValueError("agent steps must be between 1 and 10")
        if counts_model_calls and max_steps > MAX_MODEL_CALLS_PER_RUN:
            raise ValueError(
                "a model-driven Agent is limited to {} calls per run".format(
                    MAX_MODEL_CALLS_PER_RUN
                )
            )
        self.root = Path(root)
        self.decide = decide
        self.provider_name = provider_name
        self.model_version = model_version
        self.max_steps = max_steps
        self.report_builder = report_builder
        self.counts_model_calls = counts_model_calls
        self.report_counts_model_calls = report_counts_model_calls
        self.factor_store = store or JsonlFactorStore(self.root)
        self.trace_store = trace_store or JsonlAgentTraceStore(self.root)

    def __call__(self, request: AgentRequest) -> AgentRunOutcome:
        analysis = analyze_asset(request.asset)
        catalog = build_evidence_catalog(request.judgment.asset, analysis.evidence)
        registry = build_research_tool_registry(
            self.root,
            request.frame,
            request.judgment,
            evidence=analysis.evidence,
            guidance=request.guidance,
            store=self.factor_store,
            as_of_cutoff=request.replay_cutoff,
        )
        context = build_agent_context(request, catalog)
        context["allowed_tools"] = registry.describe()
        context["allowed_actions"] = list(AGENT_ACTIONS)
        trace_id = "{}:{}".format(request.judgment.asset, request.frame.frame_id)
        try:
            run = AgentLoop(registry, self.max_steps).run(
                context, self.decide, trace_id, request.frame.frame_id
            )
        except ValueError as exc:
            # A rejected decision is recorded and the frame is skipped. The error is
            # never repaired, retried with different facts, or replaced by a report.
            return self._failed_run(request, trace_id, str(exc), model_calls=1)
        decisions = run.trace.decisions
        terminal = decisions[-1]
        terminal_action = terminal.action.action
        factor_ids = _created_hypothesis_ids(decisions)
        # finish and generate_factor both produce research output; monitor and
        # wait_for_confirmation deliberately stop before the strong analyst.
        escalated = terminal_action in ESCALATING_ACTIONS
        error = None
        report = None
        report_attempted = escalated and self.report_builder is not None
        if report_attempted:
            try:
                report = self.report_builder(request)
            except ValueError as exc:
                # The strong analyst failed. Keep the error instead of a report.
                error = str(exc)
                escalated = False
        summary = self._summary(
            request=request,
            trace_id=trace_id,
            trace=run.trace,
            decisions=decisions,
            terminal_action=terminal_action,
            terminal_reason=terminal.action.reason,
            within_budget=run.within_budget,
            confidence=terminal.action.confidence,
            factor_ids=factor_ids,
            report=report,
            error=error,
            report_model_calls=(
                1 if report_attempted and self.report_counts_model_calls else 0
            ),
        )
        return self._finish(summary, report, factor_ids, escalated)

    def _failed_run(self, request: AgentRequest, trace_id: str, error: str, model_calls: int):
        summary = self._summary(
            request=request,
            trace_id=trace_id,
            trace=AgentTrace(trace_id=trace_id, frame_id=request.frame.frame_id),
            decisions=[],
            terminal_action="rejected",
            terminal_reason=error,
            within_budget=True,
            confidence=0.0,
            factor_ids=[],
            report=None,
            error=error,
            model_calls=model_calls,
        )
        return self._finish(summary, None, [], False)

    def _summary(
        self,
        request: AgentRequest,
        trace_id: str,
        trace: AgentTrace,
        decisions,
        terminal_action: str,
        terminal_reason: str,
        within_budget: bool,
        confidence: float,
        factor_ids: List[str],
        report: Optional[MarketReport],
        error: Optional[str],
        model_calls: Optional[int] = None,
        report_model_calls: int = 0,
    ) -> AgentRunSummary:
        decision_calls = model_calls
        if decision_calls is None:
            decision_calls = len(decisions) if self.counts_model_calls else 0
        return AgentRunSummary(
            trace_id=trace_id,
            frame_id=request.frame.frame_id,
            asset=request.judgment.asset,
            as_of=request.judgment.as_of,
            provider=request.judgment.provider,
            model_version=request.judgment.model_version,
            context_state=request.judgment.selected_value,
            research_priority=request.judgment.research_priority,
            decision_provider=self.provider_name,
            steps=len(decisions),
            model_calls=decision_calls + report_model_calls,
            actions=[item.action.action for item in decisions],
            tool_names=[item.action.tool_name for item in decisions if item.action.tool_name],
            failed_tools=[
                item.action.tool_name
                for item in decisions
                if item.tool_result is not None and not item.tool_result.ok
            ],
            terminal_action=terminal_action,
            terminal_reason=terminal_reason,
            terminal_within_budget=within_budget,
            confidence=confidence,
            factor_hypothesis_ids=factor_ids,
            report_headline=report.headline if report else None,
            error=error,
            created_at=_now(),
            trace=trace,
        )

    def _finish(
        self,
        summary: AgentRunSummary,
        report: Optional[MarketReport],
        factor_ids: List[str],
        escalated: bool,
    ) -> AgentRunOutcome:
        self.trace_store.append(summary)
        return AgentRunOutcome(
            summary=summary,
            report=report,
            factor_hypotheses=_hypotheses_by_id(self.factor_store, factor_ids),
            escalated=escalated,
        )


def build_agent_context(request: AgentRequest, catalog) -> dict[str, Any]:
    """Build the frozen, model-readable context for one Agent run."""
    judgment = request.judgment
    frame = request.frame
    trend = request.trend
    guidance = request.guidance
    return {
        "asset": judgment.asset,
        "as_of": judgment.as_of,
        "frame_id": judgment.frame_id,
        "regime": judgment.selected_value,
        "regime_probability": judgment.probabilities.get(judgment.selected_value),
        "confidence": judgment.confidence,
        "research_priority": judgment.research_priority,
        "contradicting_roles": list(judgment.contradicting_roles),
        "missing_roles": list(judgment.missing_roles),
        "invalidation_conditions": list(judgment.invalidation_conditions),
        "evidence_catalog": [item.model_dump() for item in catalog],
        "market_state": {
            "price": frame.price_state,
            "spot": frame.spot_state,
            "leverage": frame.leverage_state,
            "anomalies": frame.anomalies,
            "missing_inputs": frame.missing_inputs,
            "quality": frame.quality_summary,
        },
        "trend": {
            "consecutive_state_frames": trend.consecutive_state_frames,
            "state_flips_12": trend.state_flips_12,
            "probability_delta_1": trend.probability_delta_1,
            "probability_delta_3": trend.probability_delta_3,
            "probability_delta_12": trend.probability_delta_12,
        },
        "guidance": {
            "action": guidance.action,
            "focus": list(guidance.focus),
            "factor_candidates": list(guidance.factor_candidates),
            "invalidation_conditions": list(guidance.invalidation_conditions),
        },
        "factor_candidates": list(guidance.factor_candidates),
        "gate_reason": request.gate_reason,
        "related_memory": request.memory_context,
    }


def _created_hypothesis_ids(decisions) -> List[str]:
    ids = []
    for decision in decisions:
        result: Optional[ToolResult] = decision.tool_result
        if result is None or not result.ok or result.tool_name != "create_factor_hypothesis":
            continue
        if isinstance(result.data, dict) and result.data.get("hypothesis_id"):
            ids.append(str(result.data["hypothesis_id"]))
    return ids


def _hypotheses_by_id(store: JsonlFactorStore, ids: List[str]) -> List[FactorHypothesis]:
    if not ids:
        return []
    wanted = set(ids)
    stored = {item.hypothesis_id: item for item in store.hypotheses()}
    return [stored[item] for item in ids if item in stored]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
