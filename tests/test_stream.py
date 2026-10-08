import io
import json

from tellagent.data import load_fixture
from tellagent.stream import observe_snapshot, run_observer


def test_observer_stream_emits_jsonl_for_finite_cycles():
    output = io.StringIO()
    snapshot = load_fixture()
    completed = run_observer(lambda: snapshot, asset="ETH", cycles=2, interval=0, output=output)
    lines = output.getvalue().splitlines()
    assert completed == 2
    assert len(lines) == 2
    record = json.loads(lines[0])
    assert record["asset"] == "ETH"
    assert record["provider"] == "rule-based-jev"


def test_observe_snapshot_rejects_unknown_asset():
    snapshot = load_fixture()
    try:
        observe_snapshot(snapshot, asset="SOL")
    except ValueError as exc:
        assert "Asset not found" in str(exc)
    else:
        raise AssertionError("Unknown asset should fail")
