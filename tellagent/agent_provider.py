import json
import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from .agent_schemas import AGENT_ACTIONS, TERMINAL_ACTIONS, AgentDecision, ToolResult
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


SYSTEM_PROMPT = (
    "You are a constrained crypto market research Agent. Return JSON only. "
    "Choose exactly one allowed action per step: monitor, investigate, compare_history, "
    "generate_factor, wait_for_confirmation, or finish. "
    "monitor, wait_for_confirmation and finish are terminal: they end the run and must not "
    "invoke a tool. Use the read-only tools to check history before escalating. "
    "finish means the frame deserves a full research report; monitor means the frame is not "
    "worth reporting; wait_for_confirmation means key evidence is still missing. "
    "Each step you receive steps_remaining and previous_steps. When steps_remaining is 0 you "
    "MUST choose a terminal action. Never repeat a tool call that already appears in "
    "previous_steps with the same arguments; read previous_steps before deciding. "
    "You may inspect market state and tool results, but never invent facts, never trade, "
    "never ask for Shell, Python or network access, and never request an unknown tool. "
    "Required JSON fields: step, action, reason, confidence, tool_name, tool_args, finished."
)


def _normalize_decision(fields: Any, step: int) -> Any:
    """Repair the model's JSON shape without relaxing any real constraint.

    Models routinely return the step as a string or serialize ``tool_args`` as a
    JSON string. Normalizing those shapes keeps the run alive; the action
    allowlist, terminal rules, tool allowlist and every argument check still
    apply afterwards.
    """
    if not isinstance(fields, dict):
        return fields
    fields = dict(fields)
    action = fields.get("action")
    if not isinstance(action, dict):
        return fields
    action = dict(action)
    raw_args = action.get("tool_args")
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError:
            parsed = {}
        raw_args = parsed
    action["tool_args"] = raw_args if isinstance(raw_args, dict) else {}
    if action.get("tool_name") == "":
        action["tool_name"] = None
    fields["action"] = action
    if not isinstance(fields.get("step"), int):
        try:
            fields["step"] = int(str(fields.get("step")).strip())
        except (TypeError, ValueError):
            fields["step"] = step
    return fields


class RemoteAgentProvider:
    """DeepSeek-compatible structured Agent decision provider."""

    provider = "remote-agent"
    counts_model_calls = True

    def __init__(
        self,
        config: RemoteAgentConfig,
        registry: Optional[ToolRegistry] = None,
        client: Optional[httpx.Client] = None,
    ):
        self.config = config
        self.registry = registry
        self.model_version = config.model
        self.client = client

    def decide(self, context: dict[str, Any], tool_result: Optional[ToolResult], step: int) -> AgentDecision:
        allowed_tools = context.get("allowed_tools")
        if not allowed_tools:
            allowed_tools = self.registry.describe() if self.registry is not None else []
        allowed_actions = context.get("allowed_actions") or list(AGENT_ACTIONS)
        payload = {
            "model": self.config.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps({
                        "step": step,
                        "context": context,
                        "previous_tool_result": tool_result.model_dump() if tool_result else None,
                        "allowed_tools": allowed_tools,
                        "allowed_actions": allowed_actions,
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
            if isinstance(fields, list) and fields and isinstance(fields[0], dict):
                fields = fields[0]
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
            fields = _normalize_decision(fields, step)
            decision = AgentDecision.model_validate(fields)
            if decision.step != step:
                raise ValueError("Agent returned step {}, expected {}".format(decision.step, step))
            if context.get("steps_remaining") == 0 and decision.action.action not in TERMINAL_ACTIONS:
                raise ValueError(
                    "Agent must choose a terminal action on the last step, got {}".format(
                        decision.action.action
                    )
                )
            known_tools = {item["name"] for item in allowed_tools}
            if decision.action.tool_name is not None and decision.action.tool_name not in known_tools:
                raise ValueError("Agent selected an unregistered tool: {}".format(decision.action.tool_name))
            return decision
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Remote Agent failed: {}".format(exc)) from exc
        finally:
            if owns_client:
                client.close()
