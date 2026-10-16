import json

import httpx

from tellagent.agent_provider import RemoteAgentConfig, RemoteAgentProvider
from tellagent.tools import ToolRegistry


def test_remote_agent_returns_valid_decision_and_sees_tools():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        user = json.loads(body["messages"][1]["content"])
        assert user["allowed_actions"]
        assert user["allowed_tools"][0]["name"] == "history"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "step": 1,
            "action": "compare_history",
            "reason": "state deserves context",
            "confidence": 0.8,
            "tool_name": "history",
            "tool_args": {"limit": 3},
            "finished": False,
        })}}]})

    registry = ToolRegistry()
    registry.register("history", "Read history", lambda args: {})
    provider = RemoteAgentProvider(
        RemoteAgentConfig("https://model.test/chat", "key", "deepseek-test"),
        registry,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    decision = provider.decide({"regime": "conflicting"}, None, 1)
    assert decision.action.action == "compare_history"
    assert decision.action.tool_name == "history"


def test_remote_agent_rejects_unregistered_tool():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "step": 1, "action": "investigate", "reason": "x", "confidence": 0.7,
            "tool_name": "shell", "tool_args": {}, "finished": False,
        })}}]})

    provider = RemoteAgentProvider(
        RemoteAgentConfig("https://model.test/chat", "key", "deepseek-test"),
        ToolRegistry(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    try:
        provider.decide({}, None, 1)
    except ValueError as exc:
        assert "unregistered tool" in str(exc)
    else:
        raise AssertionError("Unknown Agent tool should be rejected")
