import pytest

from tellagent.observer import RuleBasedObserver, build_state_frame
from tellagent.schemas import AssetSnapshot, MarketSnapshot
from helpers import market_snapshot


def test_rule_observer_scores_are_continuous_and_confidence_is_bounded():
    snapshot = market_snapshot()
    judgment = RuleBasedObserver().judge(build_state_frame(snapshot, snapshot.assets[1]))
    assert judgment.score_kind == "heuristic"
    assert sum(judgment.probabilities.values()) == 1.0
    assert 0 < judgment.confidence <= 1


def test_conflicting_assessment_reduces_rule_confidence():
    snapshot = market_snapshot()
    asset = snapshot.assets[0].model_copy(update={
        "price_change_1h": 0.04,
        "spot_volume_change_1h": 0.09,
        "spot_volume_ratio_6h": 2.0,
        "open_interest_change_interval": 0.03,
    })
    frame = build_state_frame(snapshot.model_copy(update={"assets": [asset]}), asset)
    judgment = RuleBasedObserver().judge(frame)
    assert judgment.selected_value == "broad_participation_up"
    assert judgment.confidence <= 0.75


@pytest.mark.parametrize(
    ("price", "volume", "oi"),
    [
        (0.0005, 0.01, 0.03),    # flat + expanding
        (0.0005, 0.10, 0.0),     # flat + strong spot
        (0.0005, -0.02, -0.03),  # flat + contracting
        (0.0005, 0.0, 0.0),      # quiet
        (0.03, 0.01, 0.02),      # leverage expansion
        (-0.03, 0.08, 0.02),     # broad participation down
    ],
)
def test_selected_regime_is_the_highest_probability(price, volume, oi):
    asset = AssetSnapshot(
        symbol="BTC", price_change_1h=price, spot_volume_change_1h=volume,
        spot_volume_ratio_6h=2.0 if volume >= 0.08 else None,
        funding_rate=0.0001, open_interest_change_interval=oi,
    )
    snapshot = MarketSnapshot(
        as_of="2026-10-17T00:00:00Z", sources=["test"], assets=[asset],
    )
    judgment = RuleBasedObserver().judge(build_state_frame(snapshot, asset))
    assert judgment.probabilities[judgment.selected_value] > 0
    assert judgment.selected_value == max(
        judgment.probabilities, key=judgment.probabilities.get
    )
