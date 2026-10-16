from typing import Any, Dict, Literal, List, Optional, get_args

from pydantic import BaseModel, ConfigDict, Field


AgentActionName = Literal[
    "monitor",
    "investigate",
    "compare_history",
    "generate_factor",
    "wait_for_confirmation",
    "finish",
]

AGENT_ACTIONS = get_args(AgentActionName)
TERMINAL_ACTIONS = frozenset({"finish", "monitor", "wait_for_confirmation"})


class AgentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: AgentActionName
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    tool_name: Optional[str] = None
    tool_args: Dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    tool_name: str
    ok: bool
    data: Any = None
    error: Optional[str] = None


class AgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int = Field(ge=1)
    action: AgentAction
    tool_result: Optional[ToolResult] = None
    finished: bool = False


class AgentTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    frame_id: str
    decisions: List[AgentDecision] = Field(default_factory=list)


class AgentRunSummary(BaseModel):
    """Replayable record of one bounded Agent run over one MarketStateFrame."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str
    frame_id: str
    asset: str
    as_of: str
    provider: str
    model_version: str
    context_state: str
    research_priority: str
    decision_provider: str
    steps: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    actions: List[str] = Field(default_factory=list)
    tool_names: List[str] = Field(default_factory=list)
    failed_tools: List[str] = Field(default_factory=list)
    terminal_action: str
    terminal_reason: str
    terminal_within_budget: bool
    confidence: float = Field(ge=0, le=1)
    factor_hypothesis_ids: List[str] = Field(default_factory=list)
    report_headline: Optional[str] = None
    error: Optional[str] = None
    created_at: str
    trace: AgentTrace


class AgentStats(BaseModel):
    """Aggregated Agent behaviour used for evaluation, not for trading."""

    model_config = ConfigDict(extra="forbid")

    run_count: int = Field(ge=0)
    average_steps: float = Field(ge=0)
    average_tool_calls: float = Field(ge=0)
    average_model_calls: float = Field(ge=0)
    finish_rate: float = Field(ge=0, le=1)
    tool_success_rate: float = Field(ge=0, le=1)
    action_counts: Dict[str, int] = Field(default_factory=dict)
    tool_counts: Dict[str, int] = Field(default_factory=dict)
    terminal_counts: Dict[str, int] = Field(default_factory=dict)
