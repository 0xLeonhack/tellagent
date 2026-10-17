from tellagent.observer import RuleBasedObserver, build_state_frame
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
        "open_interest_change_interval": 0.03,
    })
    frame = build_state_frame(snapshot.model_copy(update={"assets": [asset]}), asset)
    judgment = RuleBasedObserver().judge(frame)
    assert judgment.selected_value == "broad_participation_up"
    assert judgment.confidence <= 0.75
