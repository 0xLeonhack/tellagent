from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class AssetSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    price_change_1h: Optional[float] = None
    price_change_6h: Optional[float] = None
    spot_volume_change_1h: Optional[float] = None
    funding_rate: Optional[float] = None
    open_interest_change_1h: Optional[float] = None


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: str
    sources: List[str] = Field(min_length=1)
    assets: List[AssetSnapshot] = Field(min_length=1)


class EvidenceBundle(BaseModel):
    supporting: List[str] = Field(default_factory=list)
    contradicting: List[str] = Field(default_factory=list)
    missing: List[str] = Field(default_factory=list)


class AnalystResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1)
    state: Literal["leverage_led", "spot_confirmed", "deleveraging", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    supporting_evidence: List[str] = Field(min_length=1)
    contradicting_evidence: List[str] = Field(min_length=1)
    missing_evidence: List[str] = Field(default_factory=list)
    invalidation_condition: str = Field(min_length=1)


class MarketReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: str
    metrics: AssetSnapshot
    headline: str = Field(min_length=1)
    state: Literal["leverage_led", "spot_confirmed", "deleveraging", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    supporting_evidence: List[str] = Field(min_length=1)
    contradicting_evidence: List[str] = Field(min_length=1)
    missing_evidence: List[str] = Field(default_factory=list)
    invalidation_condition: str = Field(min_length=1)
    data_time: str
    sources: List[str] = Field(min_length=1)


class SnapshotAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: AssetSnapshot
    evidence: EvidenceBundle
    suggested_state: Literal["leverage_led", "spot_confirmed", "deleveraging", "uncertain"]
    quality_notes: List[str] = Field(default_factory=list)


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
    schema_version: str = "demo.market-state.v1"


class ContinuousJudgment(BaseModel):
    """One structured Observer answer for one MarketStateFrame."""

    model_config = ConfigDict(extra="forbid")

    frame_id: str
    asset: str
    as_of: str
    question_set_version: str = "demo.observer.v1"
    selected_value: str
    probabilities: Dict[str, float]
    confidence: float = Field(ge=0, le=1)
    supporting_roles: List[str] = Field(default_factory=list)
    contradicting_roles: List[str] = Field(default_factory=list)
    missing_roles: List[str] = Field(default_factory=list)
    research_priority: Literal["silent", "watch", "significant", "urgent"]
    invalidation_conditions: List[str] = Field(default_factory=list)
    provider: str
    model_version: str
    latency_ms: int = Field(ge=0)
    created_at: str


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
