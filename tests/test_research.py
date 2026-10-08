from tellagent.analyst import generate_demo_report
from tellagent.data import load_fixture
from tellagent.memory import JsonlMemory
from tellagent.research import process_snapshot


def test_research_pipeline_calls_report_generator_for_significant_judgment(tmp_path):
    snapshot = load_fixture()
    calls = []

    def generator(snapshot, asset):
        calls.append(asset.symbol)
        return generate_demo_report(snapshot, asset)

    outcomes = process_snapshot(snapshot, JsonlMemory(tmp_path / "memory.jsonl"), generator, asset="ETH")
    assert len(calls) == 1
    assert calls == ["ETH"]
    assert outcomes[0].investigated is True
    assert outcomes[0].report is not None
    assert outcomes[0].memory_record is not None


def test_research_pipeline_skips_strong_model_for_uncertain_snapshot(tmp_path):
    snapshot = load_fixture()
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
