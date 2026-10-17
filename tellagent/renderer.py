from typing import Iterable

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .agent_schemas import AgentRunSummary, AgentStats
from .research import ResearchOutcome
from .schemas import MarketReport


PRIORITY_LABELS = {
    "silent": "静默",
    "watch": "观察",
    "significant": "重要",
    "urgent": "紧急",
}
PRIORITY_STYLES = {
    "silent": "dim",
    "watch": "yellow",
    "significant": "bold bright_yellow",
    "urgent": "bold red",
}
ACTION_LABELS = {
    "monitor": "继续观察",
    "investigate": "深入研究",
    "compare_history": "对比历史",
    "generate_factor": "生成因子",
    "wait_for_confirmation": "等待确认",
    "finish": "完成研究",
    "investigate_now": "立即研究",
}


def render_reports(outcomes: Iterable[ResearchOutcome], console: Console = None) -> None:
    console = console or Console()
    outcomes = list(outcomes)
    console.print()
    console.rule("[bold cyan]tellagent[/bold cyan]  市场研究", style="cyan")
    console.print("[dim]研究辅助 · 非交易建议[/dim]")
    if not outcomes:
        console.print("[yellow]本轮没有可展示的市场结果。[/yellow]")
        return

    for index, outcome in enumerate(outcomes):
        if index:
            console.print()
        _print_outcome(console, outcome)


def render_agent_stats(stats: AgentStats, console: Console = None) -> None:
    console = console or Console()
    console.print()
    console.rule("[bold cyan]tellagent[/bold cyan]  Agent 行为统计", style="cyan")
    if stats.run_count == 0:
        console.print("[yellow]还没有 Agent 运行记录。先运行 `uv run python -m tellagent agent`。[/yellow]")
        return

    overview = Table.grid(expand=True, padding=(0, 1))
    for _ in range(3):
        overview.add_column(ratio=1)
    overview.add_row(
        _stat("运行次数", str(stats.run_count)),
        _stat("平均步骤", "{:.2f}".format(stats.average_steps)),
        _stat("平均模型调用", "{:.2f}".format(stats.average_model_calls)),
    )
    overview.add_row(
        _stat("平均工具调用", "{:.2f}".format(stats.average_tool_calls)),
        _stat("报告升级率", "{:.0%}".format(stats.finish_rate)),
        _stat("工具成功率", "{:.0%}".format(stats.tool_success_rate)),
    )
    console.print(Panel(overview, title="运行概览", border_style="cyan", box=box.ROUNDED))

    distributions = Table(box=box.SIMPLE, expand=True, show_edge=False)
    distributions.add_column("分布", style="bold", width=12)
    distributions.add_column("计数")
    _add_counts_row(distributions, "动作", stats.action_counts)
    _add_counts_row(distributions, "工具", stats.tool_counts)
    _add_counts_row(distributions, "终止方式", stats.terminal_counts)
    console.print(distributions)


def _print_outcome(console: Console, outcome: ResearchOutcome) -> None:
    judgment = outcome.judgment
    report = outcome.report
    priority = PRIORITY_LABELS.get(judgment.research_priority, judgment.research_priority)
    priority_style = PRIORITY_STYLES.get(judgment.research_priority, "white")
    decision = "已生成研究报告" if report else "仅观察，未生成报告"
    if outcome.agent_run is not None and report is None:
        decision = "Agent 决定{}".format(
            ACTION_LABELS.get(outcome.agent_run.terminal_action, outcome.agent_run.terminal_action)
        )

    summary = Table.grid(expand=True, padding=(0, 1))
    summary.add_column(ratio=2)
    summary.add_column(ratio=1)
    summary.add_column(ratio=1)
    summary.add_column(ratio=2)
    summary.add_row(
        _stat("市场状态", judgment.selected_value, "bold white"),
        _stat("置信度", "{:.0%}".format(judgment.confidence)),
        _stat("优先级", priority, priority_style),
        _stat("本轮处理", decision, "green" if report else "dim"),
    )
    console.print(Panel(
        summary,
        title="[bold]{}[/bold]".format(judgment.asset),
        subtitle="{} · {}".format(judgment.provider, judgment.as_of),
        border_style=_priority_border(judgment.research_priority),
        box=box.ROUNDED,
    ))

    headline = report.headline if report else _observation_headline(outcome)
    console.print(Panel(
        Text(headline, style="bold"),
        title="结论",
        border_style="green" if report else "bright_black",
        box=box.SIMPLE,
        padding=(0, 1),
    ))

    if report is not None:
        _print_metrics(console, report)
    _print_signal_context(console, outcome)
    if outcome.agent_run is not None:
        _print_agent_run(console, outcome.agent_run)
    if report is not None:
        _print_evidence(console, report)
        console.print("[bold]失效条件[/bold] ", Text(report.invalidation_condition))
        console.print("[dim]来源 {} · 数据时间 {}[/dim]".format(", ".join(report.sources), report.data_time))


def _print_metrics(console: Console, report: MarketReport) -> None:
    metrics = report.metrics
    table = Table(box=box.SIMPLE_HEAD, expand=True, show_edge=False, pad_edge=False)
    table.add_column("价格 1h", justify="right")
    table.add_column("价格 6h", justify="right")
    table.add_column("现货量 1h", justify="right")
    table.add_column("Funding", justify="right")
    table.add_column("OI 本轮", justify="right")
    table.add_column("Open Interest", justify="right")
    table.add_row(
        _colored_percent(metrics.price_change_1h),
        _colored_percent(metrics.price_change_6h),
        _colored_percent(metrics.spot_volume_change_1h),
        _colored_percent(metrics.funding_rate, digits=4),
        _colored_percent(metrics.open_interest_change_interval),
        _format_number(metrics.open_interest),
    )
    console.print(table)


def _print_signal_context(console: Console, outcome: ResearchOutcome) -> None:
    judgment = outcome.judgment
    top_scores = sorted(judgment.probabilities.items(), key=lambda item: item[1], reverse=True)[:3]
    score_label = "概率" if judgment.score_kind == "probability" else "启发式分数"
    score_text = "  ·  ".join("{} {:.0%}".format(name, value) for name, value in top_scores)

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(style="bold", width=12)
    table.add_column(ratio=1)
    table.add_row(score_label, score_text or "无")
    table.add_row(
        "状态趋势",
        "持续 {} 帧  ·  近 12 帧翻转 {} 次".format(
            outcome.trend.consecutive_state_frames, outcome.trend.state_flips_12
        ),
    )
    table.add_row("研究重点", "；".join(outcome.guidance.focus) or "无")
    if outcome.guidance.factor_candidates:
        table.add_row("因子候选", "、".join(outcome.guidance.factor_candidates))
    if judgment.contradicting_roles:
        table.add_row("冲突信号", "、".join(judgment.contradicting_roles))
    if judgment.missing_roles:
        table.add_row("缺失数据", "、".join(judgment.missing_roles))
    console.print(Panel(table, title="Observer 判断 · 研究建议", border_style="bright_black", box=box.ROUNDED))


def _print_agent_run(console: Console, summary: AgentRunSummary) -> None:
    table = Table(box=box.SIMPLE_HEAD, expand=True, show_edge=False, pad_edge=False)
    table.add_column("步", justify="right", width=3)
    table.add_column("动作", style="bold", width=12)
    table.add_column("工具 / 结果", width=22, overflow="fold")
    table.add_column("理由", ratio=1, overflow="fold")
    for decision in summary.trace.decisions:
        action = ACTION_LABELS.get(decision.action.action, decision.action.action)
        tool_text = Text("—")
        if decision.action.tool_name:
            result = decision.tool_result
            succeeded = result is not None and result.ok
            detail = _tool_detail(result)
            tool_text = Text(decision.action.tool_name + "  ")
            tool_text.append("成功" if succeeded else "失败", style="green" if succeeded else "red")
            if detail:
                tool_text.append("\n" + detail, style="dim")
        table.add_row(str(decision.step), action, tool_text, Text(decision.action.reason))

    provider = "{} · {} 步 · 模型调用 {} 次 · 置信度 {:.0%}".format(
        summary.decision_provider, summary.steps, summary.model_calls, summary.confidence
    )
    footer = Text.from_markup("[dim]{}[/dim]".format(provider))
    if not summary.terminal_within_budget:
        footer.append("\n步数预算用尽后自动结束", style="yellow")
    if summary.factor_hypothesis_ids:
        footer.append("\n因子假设  {}".format("、".join(summary.factor_hypothesis_ids)), style="cyan")
    if summary.error:
        footer.append("\n错误  {}".format(summary.error), style="bold red")
    console.print(Panel(
        Group(table, footer),
        title="Agent 研究轨迹",
        subtitle="trace {}".format(summary.trace_id),
        border_style="blue",
        box=box.ROUNDED,
    ))


def _print_evidence(console: Console, report: MarketReport) -> None:
    table = Table(box=box.SIMPLE, expand=True, show_edge=False, pad_edge=False)
    table.add_column("类型", width=10)
    table.add_column("证据")
    groups = (
        ("[green]支持[/green]", report.supporting_evidence),
        ("[yellow]反向[/yellow]", report.contradicting_evidence),
        ("[magenta]缺失[/magenta]", report.missing_evidence),
    )
    for label, items in groups:
        for index, item in enumerate(items):
            table.add_row(label if index == 0 else "", Text(item))
    console.print(Panel(table, title="证据清单", border_style="bright_black", box=box.ROUNDED))


def _observation_headline(outcome: ResearchOutcome) -> str:
    action = ACTION_LABELS.get(outcome.guidance.action, outcome.guidance.action)
    if outcome.agent_run is not None:
        return "{}；本轮未升级为完整报告。".format(outcome.agent_run.terminal_reason)
    return "当前状态不满足强分析触发条件；建议{}。".format(action)


def _stat(label: str, value: str, style: str = "bold cyan") -> Text:
    text = Text()
    text.append(label + "\n", style="dim")
    text.append(value, style=style)
    return text


def _add_counts_row(table: Table, label: str, counts) -> None:
    value = "  ·  ".join("{} {}".format(name, count) for name, count in counts.items()) if counts else "无"
    table.add_row(label, value)


def _priority_border(priority: str) -> str:
    return {
        "silent": "bright_black",
        "watch": "yellow",
        "significant": "bright_yellow",
        "urgent": "red",
    }.get(priority, "cyan")


def _tool_detail(result) -> str:
    if result is None:
        return "未返回结果"
    if not result.ok:
        return result.error or "未知错误"
    data = result.data
    if isinstance(data, dict) and "count" in data:
        return "{} 条记录".format(data["count"])
    if isinstance(data, dict) and "created" in data:
        return str(data.get("hypothesis_id", "已创建"))
    if isinstance(data, dict) and "available" in data:
        return "数据可用" if data["available"] else "数据缺失"
    return "完成"


def _colored_percent(value, digits: int = 2) -> Text:
    formatted = _format_percent(value, digits)
    if value is None:
        return Text(formatted, style="dim")
    style = "green" if value > 0 else "red" if value < 0 else "white"
    return Text(formatted, style=style)


def _format_percent(value, digits: int = 2) -> str:
    if value is None:
        return "缺失"
    return ("{:+." + str(digits) + "f}%").format(value * 100)


def _format_number(value) -> str:
    if value is None:
        return "缺失"
    return "{:,.2f}".format(value)
