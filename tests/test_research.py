from tellagent.memory import JsonlMemory
from tellagent.metrics import build_deterministic_report
from tellagent.research import _event_is_open, process_snapshot, run_research
from tellagent.schemas import MarketReport
from tellagent.renderer import render_reports
from helpers import market_snapshot


class _StubLedger:
    def __init__(self, decisions):
        self._decisions = decisions

    def gate_decisions(self, asset=None):
        return self._decisions


def test_event_stays_open_across_silent_frames():
    decisions = [
        {"action": "open_event", "event_key": "BTC:quiet"},
        {"action": "silent", "event_key": "BTC:quiet"},
    ]
    ledger = _StubLedger(decisions)

    assert _event_is_open(ledger, "BTC", "quiet")
    assert not _event_is_open(ledger, "BTC", "conflicting")

    decisions.append({"action": "open_event", "event_key": "BTC:conflicting"})
    # A newer event supersedes the old one.
    assert not _event_is_open(ledger, "BTC", "quiet")
    assert _event_is_open(ledger, "BTC", "conflicting")


def test_research_pipeline_calls_report_generator_for_significant_judgment(tmp_path):
    snapshot = market_snapshot()
    calls = []

    def generator(snapshot, asset):
        calls.append(asset.symbol)
        return MarketReport(
            asset=asset.symbol, metrics=asset, headline="test report", state="leverage_expansion_up",
            confidence=0.8, supporting_evidence=["test"], contradicting_evidence=["counter"],
            missing_evidence=[], invalidation_condition="test", data_time=snapshot.as_of,
            sources=snapshot.sources,
        )

    outcomes = process_snapshot(snapshot, JsonlMemory(tmp_path / "memory.jsonl"), generator, asset="ETH")
    assert len(calls) == 1
    assert calls == ["ETH"]
    assert outcomes[0].investigated is True
    assert outcomes[0].report is not None
    assert outcomes[0].memory_record is not None
    assert outcomes[0].guidance.action == "investigate_now"


def test_contextual_report_generator_receives_the_frozen_frame(tmp_path):
    snapshot = market_snapshot()
    seen = []

    def generator(current, asset, judgment, frame, context):
        seen.append(frame.frame_id)
        return build_deterministic_report(
            current,
            asset,
            judgment=judgment,
            assessment=frame.assessment,
        )

    outcomes = process_snapshot(
        snapshot,
        JsonlMemory(tmp_path / "memory.jsonl"),
        asset="ETH",
        contextual_report_generator=generator,
    )

    assert seen == [outcomes[0].judgment.frame_id]
    assert outcomes[0].report.state == outcomes[0].judgment.selected_value


def test_research_pipeline_skips_strong_model_for_insufficient_snapshot(tmp_path):
    snapshot = market_snapshot()
    asset = snapshot.assets[0].model_copy(update={"open_interest_change_1h": None})
    snapshot = snapshot.model_copy(update={"assets": [asset]})
    calls = []
    outcomes = process_snapshot(
        snapshot,
        JsonlMemory(tmp_path / "memory.jsonl"),
        lambda snapshot, asset: calls.append(asset.symbol),
    )
    assert calls == []
    assert outcomes[0].investigated is False
    assert outcomes[0].memory_record is None


def test_research_loop_runs_finite_cycles_and_keeps_memory(tmp_path):
    snapshot = market_snapshot()
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    seen = []
    completed = run_research(
        lambda: snapshot,
        memory,
        lambda snapshot, asset: MarketReport(
            asset=asset.symbol, metrics=asset, headline="test report", state="leverage_expansion_up",
            confidence=0.8, supporting_evidence=["test"], contradicting_evidence=["counter"],
            missing_evidence=[], invalidation_condition="test", data_time=snapshot.as_of,
            sources=snapshot.sources,
        ),
        asset="ETH",
        cycles=2,
        interval=0,
        on_cycle=lambda outcomes: seen.append(outcomes[0].investigated),
    )
    assert completed == 2
    assert seen == [True, False]
    assert len(memory.records()) == 1


def test_research_loop_can_recover_from_a_collection_error(tmp_path):
    snapshot = market_snapshot()
    attempts = 0
    errors = []

    def loader():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("temporary exchange outage")
        return snapshot

    completed = run_research(
        loader,
        JsonlMemory(tmp_path / "memory.jsonl"),
        asset="ETH",
        cycles=1,
        interval=0,
        continue_on_error=True,
        on_error=errors.append,
    )

    assert completed == 1
    assert attempts == 2
    assert errors == ["temporary exchange outage"]


def test_renderer_shows_observer_result_without_strong_report(capsys):
    snapshot = market_snapshot()
    outcomes = process_snapshot(snapshot, JsonlMemory("/tmp/tellagent-render-test.jsonl"), asset="ETH")
    render_reports(outcomes)
    output = capsys.readouterr().out
    assert "Observer 判断" in output
    assert "研究建议" in output
    assert "Jev" not in output
