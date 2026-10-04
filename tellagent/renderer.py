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
