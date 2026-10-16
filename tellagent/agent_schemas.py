from typing import Any, Dict, Literal, List, Optional

from pydantic import BaseModel, ConfigDict, Field


AgentActionName = Literal[
    "monitor",
    "investigate",
    "compare_history",
    "generate_factor",
    "wait_for_confirmation",
    "finish",
]


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
