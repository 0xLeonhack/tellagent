import pytest

from tellagent.ledger import JsonlLedger
from tellagent.memory import JsonlMemory
from tellagent.observer import RuleBasedJevObserver, build_state_frame
from tellagent.research import process_snapshot
from tellagent.review import OutcomeReviewer
from tellagent.schemas import AssetSnapshot, MarketSnapshot


def _snapshot(as_of, price, oi, oi_change, volume=0.01):
    return MarketSnapshot(
        as_of=as_of,
        sources=["test"],
        assets=[AssetSnapshot(
            symbol="ETH", spot_price=price, price_change_1h=0.04, price_change_6h=0.05,
            spot_volume_change_1h=volume, funding_rate=0.0002,
            open_interest=oi, open_interest_change_interval=oi_change,
        )],
    )


def test_outcome_reviewer_creates_due_reviews_without_model(tmp_path):
    ledger = JsonlLedger(tmp_path)
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    reviewer = OutcomeReviewer(tmp_path)
    original = _snapshot("2026-10-08T00:00:00Z", 100.0, 1000.0, 0.02)
    process_snapshot(original, memory, asset="ETH", ledger=ledger, reviewer=reviewer)
    assert len(reviewer.events()) == 1

    later = _snapshot("2026-10-08T06:00:00Z", 105.0, 950.0, -0.02, volume=0.08)
    frame = build_state_frame(later, later.assets[0])
    ledger.append_frame(later, later.assets[0], frame)
    reviews = reviewer.review_due(later, ledger)
    assert len(reviews) == 1
    assert reviews[0].horizon == "6h"
    assert reviews[0].realized_return == pytest.approx(0.05)
    assert reviews[0].open_interest_change == pytest.approx(-0.05)
    assert reviews[0].invalidation_triggered is True
    summary = reviewer.calibration_summary()
    assert summary[0].state == "leverage_led"
    assert summary[0].sample_count == 1
    assert summary[0].invalidation_rate == 1.0
    assert (tmp_path / "calibration_report.json").exists()


def test_outcome_review_is_idempotent(tmp_path):
    ledger = JsonlLedger(tmp_path)
    reviewer = OutcomeReviewer(tmp_path)
    original = _snapshot("2026-10-08T00:00:00Z", 100.0, 1000.0, 0.02)
    frame = build_state_frame(original, original.assets[0])
    judgment = RuleBasedJevObserver().judge(frame)
    reviewer.open_event(original, original.assets[0], frame, judgment, None)
    later = _snapshot("2026-10-08T06:00:00Z", 101.0, 990.0, -0.01)
    assert len(reviewer.review_due(later, ledger)) == 1
    assert reviewer.review_due(later, ledger) == []
