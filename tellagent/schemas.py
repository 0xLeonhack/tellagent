from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class AssetSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    spot_price: Optional[float] = None
    price_change_1h: Optional[float] = None
    price_change_6h: Optional[float] = None
    realized_volatility_6h: Optional[float] = None
    spot_volume_change_1h: Optional[float] = None
    spot_volume_ratio_6h: Optional[float] = None
    funding_rate: Optional[float] = None
    open_interest: Optional[float] = None
    open_interest_change_interval: Optional[float] = None
    open_interest_change_1h: Optional[float] = None
    strategy_thresholds: Dict[str, float] = Field(default_factory=dict)


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: str
    sources: List[str] = Field(min_length=1)
    assets: List[AssetSnapshot] = Field(min_length=1)
    source_times: Dict[str, str] = Field(default_factory=dict)
    payload_hashes: Dict[str, str] = Field(default_factory=dict)
    available_time: Optional[str] = None
    received_time: Optional[str] = None


class EvidenceBundle(BaseModel):
    supporting: List[str] = Field(default_factory=list)
    contradicting: List[str] = Field(default_factory=list)
    missing: List[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    role: Literal["supporting", "contradicting", "missing"]
    statement: str


class AnalystResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1)
    state: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    supporting_evidence_ids: List[str] = Field(min_length=1)
    contradicting_evidence_ids: List[str] = Field(min_length=1)
    missing_evidence_ids: List[str] = Field(default_factory=list)
    invalidation_condition: str = Field(min_length=1)


class MarketReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str
    metrics: AssetSnapshot
    headline: str = Field(min_length=1)
    state: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    supporting_evidence: List[str] = Field(min_length=1)
    contradicting_evidence: List[str] = Field(min_length=1)
    missing_evidence: List[str] = Field(default_factory=list)
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    contradicting_evidence_ids: List[str] = Field(default_factory=list)
    missing_evidence_ids: List[str] = Field(default_factory=list)
    invalidation_condition: str = Field(min_length=1)
    data_time: str
    sources: List[str] = Field(min_length=1)


class SnapshotAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: AssetSnapshot
    evidence: EvidenceBundle
    suggested_state: str
    assessment: "MarketAssessment"


class MarketAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_direction: Literal["up", "down", "flat", "unknown"]
    price_strength: Literal["quiet", "normal", "shock", "unknown"]
    leverage_change: Literal["expanding", "contracting", "stable", "unknown"]
    spot_confirmation: Literal["strong", "weak", "absent", "unknown"]
    funding_state: Literal["long_crowded", "short_crowded", "neutral", "unknown"]
    alignment: Literal["aligned", "mixed", "conflicting", "insufficient"]
    data_quality: Literal["complete", "degraded", "insufficient"]
    regime: Literal[
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
    ]
    risk_flags: List[str] = Field(default_factory=list)
    data_quality_score: float = Field(default=1.0, ge=0, le=1)
    source_alignment_seconds: Optional[int] = Field(default=None, ge=0)


class FeatureBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_count: int = Field(ge=0)
    ready: bool
    median: Optional[float] = None
    mad: Optional[float] = None
    percentile: Optional[float] = Field(default=None, ge=0, le=1)
    robust_zscore: Optional[float] = None
    p90_abs: Optional[float] = None


class MarketStateFrame(BaseModel):
    """Compact, replayable input presented to an Observer."""

    model_config = ConfigDict(extra="forbid")

    frame_id: str
    asset: str
    as_of: str
    price_state: Dict[str, Optional[float]]
    spot_state: Dict[str, Optional[float]]
    leverage_state: Dict[str, Optional[float]]
    anomalies: List[str] = Field(default_factory=list)
    missing_inputs: List[str] = Field(default_factory=list)
    quality_summary: Dict[str, str]
    baseline_state: Dict[str, FeatureBaseline] = Field(default_factory=dict)
    strategy_thresholds: Dict[str, float] = Field(default_factory=dict)
    assessment: Optional[MarketAssessment] = None
    schema_version: str = "tellagent.market-state.v2"


class ContinuousJudgment(BaseModel):
    """One structured Observer answer for one MarketStateFrame."""

    model_config = ConfigDict(extra="forbid")

    frame_id: str
    asset: str
    as_of: str
    question_set_version: str = "tellagent.observer.v1"
    selected_value: str
    probabilities: Dict[str, float]
    confidence: float = Field(ge=0, le=1)
    score_kind: Literal["heuristic", "probability"] = "probability"
    supporting_roles: List[str] = Field(default_factory=list)
    contradicting_roles: List[str] = Field(default_factory=list)
    missing_roles: List[str] = Field(default_factory=list)
    research_priority: Literal["silent", "watch", "significant", "urgent"]
    invalidation_conditions: List[str] = Field(default_factory=list)
    provider: str
    model_version: str
    latency_ms: int = Field(ge=0)
    created_at: str


class ResearchGuidance(BaseModel):
    """Non-trading next steps derived from a structured judgment."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["investigate_now", "monitor", "wait_for_confirmation"]
    focus: List[str] = Field(default_factory=list)
    factor_candidates: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)


class FrameLedgerRecord(BaseModel):
    """Immutable point-in-time record of one asset frame."""

    model_config = ConfigDict(extra="forbid")

    record_id: str
    recorded_at: str
    available_time: str
    received_time: str
    sources: List[str]
    source_times: Dict[str, str]
    payload_hashes: Dict[str, str]
    asset_snapshot: AssetSnapshot
    frame: MarketStateFrame
    feature_version: str = "tellagent.metrics.v1"


class ResearchEvent(BaseModel):
    """Frozen input for deterministic future outcome reviews."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    asset: str
    opened_at: str
    original_snapshot: AssetSnapshot
    original_frame: MarketStateFrame
    original_judgment: ContinuousJudgment
    report: Optional[MarketReport] = None
    review_due_at: Dict[str, str]


class OutcomeReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str
    event_id: str
    asset: str
    horizon: Literal["6h", "24h", "7d"]
    reviewed_at: str
    sample_time: Optional[str] = None
    sample_delay_seconds: Optional[int] = None
    status: Literal["complete", "insufficient_data"] = "complete"
    original_state: str
    realized_return: Optional[float] = None
    max_favorable_excursion: Optional[float] = None
    max_adverse_excursion: Optional[float] = None
    funding_change: Optional[float] = None
    open_interest_change: Optional[float] = None
    spot_confirmation: Optional[bool] = None
    invalidation_triggered: Optional[bool] = None


class JudgmentTrend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str
    state: str
    probability_delta_1: Optional[float] = None
    probability_delta_3: Optional[float] = None
    probability_delta_12: Optional[float] = None
    probability_ewma_12: float
    consecutive_state_frames: int = Field(ge=1)
    state_flips_12: int = Field(ge=0)
    confidence_delta_3: Optional[float] = None


class FactorHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str
    created_at: str
    source_frame_id: str
    asset: str
    name: str
    regime: str
    inputs: List[str]
    formula_draft: str
    expected_direction: str
    horizon: str
    rationale: str
    invalidation_condition: str
    test_plan: str


class FactorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: str
    hypothesis_id: str
    tested_at: str
    sample: str
    ic: Optional[float] = None
    rank_ic: Optional[float] = None
    turnover: Optional[float] = None
    cost_adjusted_return: Optional[float] = None
    max_drawdown: Optional[float] = None
    notes: str = ""


class OutcomeCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str
    horizon: Literal["6h", "24h", "7d"]
    sample_count: int = Field(ge=1)
    average_return: Optional[float] = None
    average_max_favorable_excursion: Optional[float] = None
    average_max_adverse_excursion: Optional[float] = None
    invalidation_rate: float = Field(ge=0, le=1)


class MemoryRecord(BaseModel):
    """A compact research context retained for later related judgments."""

    model_config = ConfigDict(extra="forbid")

    memory_id: str
    asset: str
    as_of: str
    state: str
    priority: str
    summary: str = Field(min_length=1)
    tags: List[str] = Field(default_factory=list)
    judgment: ContinuousJudgment
    report: Optional[MarketReport] = None
    created_at: str
