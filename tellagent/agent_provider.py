import json
import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from .agent_schemas import AgentDecision, ToolResult
from .tools import ToolRegistry


@dataclass(frozen=True)
class RemoteAgentConfig:
    api_url: str
    api_key: str
    model: str
    timeout: float = 20.0

    @classmethod
    def from_env(cls) -> "RemoteAgentConfig":
        api_url = os.getenv("TELLAGENT_MODEL_API_URL")
        api_key = os.getenv("TELLAGENT_MODEL_API_KEY")
        model = os.getenv("TELLAGENT_MODEL_NAME", "deepseek-flash")
        if not api_url or not api_key:
            raise ValueError(
                "Remote Agent requires TELLAGENT_MODEL_API_URL and "
                "TELLAGENT_MODEL_API_KEY."
            )
        return cls(api_url=api_url, api_key=api_key, model=model)


class RemoteAgentProvider:
    """DeepSeek-compatible structured Agent decision provider."""

    def __init__(
        self,
        config: RemoteAgentConfig,
        registry: ToolRegistry,
        client: Optional[httpx.Client] = None,
    ):
        self.config = config
        self.registry = registry
        self.client = client

    def decide(self, context: dict[str, Any], tool_result: Optional[ToolResult], step: int) -> AgentDecision:
        payload = {
            "model": self.config.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a constrained crypto market research Agent. Return JSON only. "
                        "Choose exactly one allowed action. You may inspect market state and tool results, "
                        "but never invent facts, trade, execute code, or request unknown tools. "
                        "Terminal actions finish the current run. Required JSON fields: step, action, "
                        "reason, confidence, tool_name, tool_args, finished."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "step": step,
                        "context": context,
                        "previous_tool_result": tool_result.model_dump() if tool_result else None,
                        "allowed_tools": self.registry.describe(),
                        "allowed_actions": [
                            "monitor", "investigate", "compare_history", "generate_factor",
                            "wait_for_confirmation", "finish",
                        ],
                    }, ensure_ascii=False),
                },
            ],
        }
        owns_client = self.client is None
        client = self.client or httpx.Client(timeout=self.config.timeout)
        try:
            response = client.post(
                self.config.api_url,
                headers={"Authorization": "Bearer " + self.config.api_key},
                json=payload,
            )
            response.raise_for_status()
            raw = response.json()
            content = raw["choices"][0]["message"]["content"]
            fields = json.loads(content) if isinstance(content, str) else content
            if isinstance(fields, dict) and isinstance(fields.get("action"), str):
                fields = {
                    "step": fields.get("step"),
                    "action": {
                        "action": fields["action"],
                        "reason": fields.get("reason", ""),
                        "confidence": fields.get("confidence", 0.0),
                        "tool_name": fields.get("tool_name"),
                        "tool_args": fields.get("tool_args", {}),
                    },
                    "finished": fields.get("finished", False),
                }
            decision = AgentDecision.model_validate(fields)
            if decision.step != step:
                raise ValueError("Agent returned step {}, expected {}".format(decision.step, step))
            if decision.action.tool_name not in {item["name"] for item in self.registry.describe()} and decision.action.tool_name is not None:
                raise ValueError("Agent selected an unregistered tool: {}".format(decision.action.tool_name))
            return decision
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Remote Agent failed: {}".format(exc)) from exc
        finally:
            if owns_client:
                client.close()
