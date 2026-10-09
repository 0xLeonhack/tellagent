from tellagent.memory import JsonlMemory
from tellagent.research import process_snapshot, run_research
from tellagent.schemas import MarketReport
from helpers import market_snapshot


def test_research_pipeline_calls_report_generator_for_significant_judgment(tmp_path):
    snapshot = market_snapshot()
    calls = []

    def generator(snapshot, asset):
        calls.append(asset.symbol)
        return MarketReport(
            asset=asset.symbol, metrics=asset, headline="test report", state="leverage_led",
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


def test_research_pipeline_skips_strong_model_for_uncertain_snapshot(tmp_path):
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
            asset=asset.symbol, metrics=asset, headline="test report", state="leverage_led",
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
