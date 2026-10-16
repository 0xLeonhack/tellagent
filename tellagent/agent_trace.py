from pathlib import Path
from typing import List, Optional

from .agent_schemas import AgentRunSummary, AgentStats


class JsonlAgentTraceStore:
    """Append-only replay log of bounded Agent runs.

    Every Action, ToolCall and ToolResult already travels inside the stored
    AgentTrace, so a run can be inspected after the fact without the model.
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    def append(self, summary: AgentRunSummary) -> Path:
        return self._append(self._path(summary.as_of), summary.model_dump_json())

    def summaries(self, asset: Optional[str] = None) -> List[AgentRunSummary]:
        directory = self.root / "agent_traces"
        if not directory.exists():
            return []
        summaries: List[AgentRunSummary] = []
        for path in sorted(directory.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                summary = AgentRunSummary.model_validate_json(line)
                if asset is None or summary.asset.upper() == asset.upper():
                    summaries.append(summary)
        return summaries

    def stats(self, asset: Optional[str] = None) -> AgentStats:
        return summarize_agent_runs(self.summaries(asset))

    def _path(self, as_of: str) -> Path:
        return self.root / "agent_traces" / "{}.jsonl".format(as_of[:10])

    @staticmethod
    def _append(path: Path, payload: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")
        return path


def summarize_agent_runs(summaries: List[AgentRunSummary]) -> AgentStats:
    """Aggregate Agent behaviour so action choice and tool cost stay observable."""
    if not summaries:
        return AgentStats(
            run_count=0,
            average_steps=0.0,
            average_tool_calls=0.0,
            average_model_calls=0.0,
            finish_rate=0.0,
            tool_success_rate=0.0,
        )
    runs = len(summaries)
    tool_calls = sum(len(item.tool_names) for item in summaries)
    failed = sum(len(item.failed_tools) for item in summaries)
    action_counts: dict[str, int] = {}
    tool_counts: dict[str, int] = {}
    terminal_counts: dict[str, int] = {}
    for item in summaries:
        for action in item.actions:
            action_counts[action] = action_counts.get(action, 0) + 1
        for name in item.tool_names:
            tool_counts[name] = tool_counts.get(name, 0) + 1
        terminal_counts[item.terminal_action] = terminal_counts.get(item.terminal_action, 0) + 1
    return AgentStats(
        run_count=runs,
        average_steps=round(sum(item.steps for item in summaries) / runs, 4),
        average_tool_calls=round(tool_calls / runs, 4),
        average_model_calls=round(sum(item.model_calls for item in summaries) / runs, 4),
        finish_rate=round(terminal_counts.get("finish", 0) / runs, 4),
        tool_success_rate=round((tool_calls - failed) / tool_calls, 4) if tool_calls else 0.0,
        action_counts=dict(sorted(action_counts.items())),
        tool_counts=dict(sorted(tool_counts.items())),
        terminal_counts=dict(sorted(terminal_counts.items())),
    )
