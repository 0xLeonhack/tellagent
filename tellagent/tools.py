from dataclasses import dataclass
from typing import Any, Callable, Dict

from .agent_schemas import ToolCall, ToolResult


ToolHandler = Callable[[Dict[str, Any]], Any]


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    description: str
    handler: ToolHandler


class ToolRegistry:
    """Static allowlist for Agent actions; unknown tools never execute."""

    def __init__(self) -> None:
        self._tools: Dict[str, RegisteredTool] = {}

    def register(self, name: str, description: str, handler: ToolHandler) -> None:
        if not name or name in self._tools:
            raise ValueError("Tool name must be non-empty and unique.")
        self._tools[name] = RegisteredTool(name, description, handler)

    def describe(self) -> list[dict[str, str]]:
        return [
            {"name": tool.name, "description": tool.description}
            for tool in self._tools.values()
        ]

    def execute(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.tool_name)
        if tool is None:
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                ok=False,
                error="Unknown tool: {}".format(call.tool_name),
            )
        try:
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                ok=True,
                data=tool.handler(call.arguments),
            )
        except (TypeError, ValueError, KeyError) as exc:
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                ok=False,
                error="Tool failed: {}".format(exc),
            )
