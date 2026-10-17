from rich.console import Console

from helpers import market_snapshot
from tellagent.memory import JsonlMemory
from tellagent.metrics import build_deterministic_report
from tellagent.renderer import render_reports
from tellagent.research import process_snapshot


def test_renderer_groups_summary_signals_and_observation(tmp_path):
    outcomes = process_snapshot(
        market_snapshot(),
        JsonlMemory(tmp_path / "memory.jsonl"),
        asset="ETH",
    )
    console = Console(record=True, width=110, color_system=None)

    render_reports(outcomes, console)

    output = console.export_text()
    assert "tellagent" in output
    assert "市场状态" in output
    assert "Observer 判断" in output
    assert "状态趋势" in output
    assert "仅观察，未生成报告" in output


def test_renderer_handles_empty_cycle():
    console = Console(record=True, width=80, color_system=None)

    render_reports([], console)

    assert "本轮没有可展示的市场结果" in console.export_text()


def test_renderer_groups_metrics_and_evidence_for_full_report(tmp_path):
    outcomes = process_snapshot(
        market_snapshot(),
        JsonlMemory(tmp_path / "memory.jsonl"),
        report_generator=build_deterministic_report,
        asset="ETH",
    )
    console = Console(record=True, width=110, color_system=None)

    render_reports(outcomes, console)

    output = console.export_text()
    assert "已生成研究报告" in output
    assert "价格 1h" in output
    assert "证据清单" in output
    assert "失效条件" in output
