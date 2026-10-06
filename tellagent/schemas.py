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
