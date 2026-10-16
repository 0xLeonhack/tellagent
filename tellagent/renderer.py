from typing import Iterable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .agent_schemas import AgentRunSummary, AgentStats
from .research import ResearchOutcome
from .schemas import ContinuousJudgment, MarketReport


def render_reports(outcomes: Iterable[ResearchOutcome], console: Console = None) -> None:
    console = console or Console()
    console.print("[bold cyan]tellagent · Market Contradiction Report[/bold cyan]")
    console.print("研究提示，不是交易建议。\n")
    for outcome in outcomes:
        _print_judgment(console, outcome.judgment)
        console.print("  • 状态持续: {} 帧 · 近 12 帧翻转: {} 次".format(
            outcome.trend.consecutive_state_frames, outcome.trend.state_flips_12
        ))
        _print_guidance(console, outcome.guidance)
        if outcome.agent_run is not None:
            _print_agent_run(console, outcome.agent_run)
        if outcome.report is not None:
            _print_report(console, outcome.report)
        elif outcome.agent_run is not None:
            console.print("[bold]结论[/bold]  Agent 未升级为完整报告：{}\n".format(
                outcome.agent_run.terminal_action
            ))


def render_agent_stats(stats: AgentStats, console: Console = None) -> None:
    console = console or Console()
    console.print("[bold cyan]tellagent · Agent 行为统计[/bold cyan]")
    console.print("来自 .tellagent/agent_traces 的可回放记录。\n")
    if stats.run_count == 0:
        console.print("还没有 Agent 运行记录。先运行 uv run python -m tellagent agent。")
        return
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_row("运行次数", str(stats.run_count))
    table.add_row("平均步数", "{:.2f}".format(stats.average_steps))
    table.add_row("平均工具调用", "{:.2f}".format(stats.average_tool_calls))
    table.add_row("平均模型调用", "{:.2f}".format(stats.average_model_calls))
    table.add_row("升级报告比例", "{:.0%}".format(stats.finish_rate))
    table.add_row("工具成功率", "{:.0%}".format(stats.tool_success_rate))
    console.print(Panel(table, title="概览", border_style="cyan"))
    _print_counts(console, "动作分布", stats.action_counts)
    _print_counts(console, "工具分布", stats.tool_counts)
    _print_counts(console, "终止动作", stats.terminal_counts)


def _print_agent_run(console: Console, summary: AgentRunSummary) -> None:
    console.print("[bold]Agent 轨迹[/bold]  {} · 决策方 {} · {} 步 · 模型调用 {} 次".format(
        summary.trace_id, summary.decision_provider, summary.steps, summary.model_calls
    ))
    for index, decision in enumerate(summary.trace.decisions, start=1):
        action = decision.action.action
        tool = decision.action.tool_name
        line = "  {}. {}  {}".format(index, action, decision.action.reason)
        console.print(line)
        if tool:
            result = decision.tool_result
            status = "ok" if result is not None and result.ok else "failed"
            detail = _tool_detail(result)
            console.print("     工具 {} → {} {}".format(tool, status, detail))
    if summary.error:
        console.print("[bold red]  Agent 错误[/bold red]  {}".format(summary.error))
    budget = "" if summary.terminal_within_budget else "（步数预算用尽后自动结束）"
    console.print("  终止: {}{} · confidence {:.0%}".format(
        summary.terminal_action, budget, summary.confidence
    ))
    if summary.factor_hypothesis_ids:
        console.print("  因子假设: {}".format("、".join(summary.factor_hypothesis_ids)))


def _tool_detail(result) -> str:
    if result is None:
        return ""
    if not result.ok:
        return result.error or ""
    data = result.data
    if isinstance(data, dict) and "count" in data:
        return "{} 条".format(data["count"])
    if isinstance(data, dict) and "created" in data:
        return str(data.get("hypothesis_id", ""))
    if isinstance(data, dict) and "available" in data:
        return "可用" if data["available"] else "缺失"
    return ""


def _print_counts(console: Console, title: str, counts) -> None:
    if not counts:
        return
    console.print("[bold]{}[/bold]  {}".format(
        title, " · ".join("{} {}".format(name, value) for name, value in counts.items())
    ))


def _print_judgment(console: Console, judgment: ContinuousJudgment) -> None:
    console.print("[bold]Observer 判断[/bold]  {} / {}".format(judgment.provider, judgment.model_version))
    console.print("  • 状态: {} (confidence {:.0%})".format(judgment.selected_value, judgment.confidence))
    console.print("  • 概率: {}".format(
        " · ".join("{} {:.2f}".format(name, value) for name, value in judgment.probabilities.items())
    ))
    console.print("  • 研究优先级: {}".format(judgment.research_priority))
    if judgment.contradicting_roles:
        console.print("  • 冲突角色: {}".format(", ".join(judgment.contradicting_roles)))
    if judgment.missing_roles:
        console.print("  • 缺失数据: {}".format("、".join(judgment.missing_roles)))


def _print_report(console: Console, report: MarketReport) -> None:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_row("数据时间", report.data_time)
    table.add_row("数据来源", ", ".join(report.sources))
    table.add_row("分析状态", "{} (confidence {:.0%})".format(report.state, report.confidence))
    console.print(Panel(table, title=report.asset, border_style="cyan"))
    metrics = report.metrics
    console.print("[bold]关键指标[/bold]")
    console.print("  • 价格变化 1h: {}".format(_format_percent(metrics.price_change_1h)))
    console.print("  • 价格变化 6h: {}".format(_format_percent(metrics.price_change_6h)))
    console.print("  • 现货成交量变化 1h: {}".format(_format_percent(metrics.spot_volume_change_1h)))
    console.print("  • funding rate: {}".format(_format_percent(metrics.funding_rate, digits=4)))
    console.print("  • open interest: {}".format(_format_number(metrics.open_interest)))
    console.print("  • open interest 本轮变化: {}".format(_format_percent(metrics.open_interest_change_interval)))
    console.print("  • open interest 变化 1h: {}".format(_format_percent(metrics.open_interest_change_1h)))
    console.print("[bold]判断[/bold]  {}".format(report.headline))
    _print_evidence(console, "支持证据", report.supporting_evidence, "green")
    _print_evidence(console, "反向证据", report.contradicting_evidence, "yellow")
    _print_evidence(console, "缺失数据", report.missing_evidence, "magenta")
    console.print("[bold]失效条件[/bold]  {}\n".format(report.invalidation_condition))


def _print_guidance(console: Console, guidance) -> None:
    console.print("[bold]研究建议[/bold]  {}".format(guidance.action))
    console.print("  • 研究重点: {}".format("、".join(guidance.focus)))
    if guidance.factor_candidates:
        console.print("  • 因子候选: {}".format("、".join(guidance.factor_candidates)))


def _print_evidence(console: Console, title: str, items, color: str) -> None:
    console.print("[bold {}]{}[/bold {}]".format(color, title, color))
    for item in items:
        console.print("  • {}".format(item))


def _format_percent(value, digits: int = 2) -> str:
    if value is None:
        return "缺失"
    return ("{:+." + str(digits) + "f}%").format(value * 100)


def _format_number(value) -> str:
    if value is None:
        return "缺失"
    return "{:,.2f}".format(value)
