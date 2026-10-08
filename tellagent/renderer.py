import json
from typing import Iterable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .schemas import MarketReport


def render_reports(reports: Iterable[MarketReport], console: Console = None) -> None:
    console = console or Console()
    console.print("[bold cyan]tellagent · Market Contradiction Report[/bold cyan]")
    console.print("研究提示，不是交易建议。\n")
    for report in reports:
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_row("数据时间", report.data_time)
        table.add_row("数据来源", ", ".join(report.sources))
        table.add_row("状态", "{} (confidence {:.0%})".format(report.state, report.confidence))
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


def render_json(reports: Iterable[MarketReport]) -> str:
    """Serialize validated reports for scripts and future UI consumers."""
    return json.dumps(
        [report.model_dump() for report in reports],
        ensure_ascii=False,
        indent=2,
    )


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
