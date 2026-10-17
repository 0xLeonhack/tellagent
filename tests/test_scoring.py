import pytest

from tellagent.assessment import assess_market
from tellagent.observer import RuleBasedObserver, build_state_frame
from tellagent.schemas import AssetSnapshot, MarketSnapshot
from tellagent.scoring import REGIMES


def _assessment(price=0.0, volume=0.0, oi=0.0, funding=0.0, seconds=None, **updates):
    asset = AssetSnapshot(
        symbol="BTC",
        price_change_1h=price,
        spot_volume_change_1h=volume,
        spot_volume_ratio_6h=2.0 if volume >= 0.05 else None,
        funding_rate=funding,
        open_interest_change_interval=oi,
        open_interest_interval_seconds=seconds,
        **updates,
    )
    return assess_market(asset), asset


def test_distribution_is_complete_and_strictly_positive():
    assessment, _ = _assessment(price=0.03, volume=0.01, oi=0.02)
    scores = assessment.regime_scores
    assert set(scores) == set(REGIMES)
    assert sum(scores.values()) == pytest.approx(1.0, abs=1e-6)
    assert all(value > 0 for value in scores.values())
    assert assessment.regime == max(scores, key=scores.get)


@pytest.mark.parametrize(
    ("price", "volume", "oi", "expected"),
    [
        (0.0001, 0.0, 0.0, "quiet"),
        (0.0005, 0.10, 0.0, "conflicting"),
        (0.0005, 0.01, 0.03, "conflicting"),
        (0.03, 0.01, 0.02, "leverage_expansion_up"),
        (-0.03, 0.01, 0.02, "leverage_expansion_down"),
        (0.03, 0.08, 0.001, "spot_confirmed_up"),
        (-0.03, 0.08, 0.001, "spot_confirmed_down"),
        (0.04, 0.09, 0.03, "broad_participation_up"),
        (-0.04, 0.09, 0.03, "broad_participation_down"),
        (-0.03, 0.0, 0.001, "unconfirmed_move_down"),
        (-0.03, 0.01, -0.02, "position_unwind_down"),
    ],
)
def test_rule_label_always_wins_the_distribution(price, volume, oi, expected):
    assessment, _ = _assessment(price=price, volume=volume, oi=oi, funding=0.0001)
    assert assessment.regime == expected
    assert expected == max(assessment.regime_scores, key=assessment.regime_scores.get)


def test_quiet_is_not_reported_as_certainty():
    assessment, _ = _assessment(price=0.0001, volume=0.0, oi=0.0)
    assert 0.5 < assessment.regime_scores["quiet"] < 0.95


def test_competing_hypotheses_keep_visible_mass():
    assessment, _ = _assessment(price=0.04, volume=0.09, oi=0.03, funding=0.0003)
    scores = assessment.regime_scores
    assert scores["broad_participation_up"] > scores["leverage_expansion_up"] > 0.1
    assert scores["spot_confirmed_up"] > 0.02


def test_more_open_interest_increases_leverage_hypothesis():
    weak, _ = _assessment(price=0.03, volume=0.01, oi=0.004)
    strong, _ = _assessment(price=0.03, volume=0.01, oi=0.03)
    assert (
        strong.regime_scores["leverage_expansion_up"]
        > weak.regime_scores["leverage_expansion_up"]
    )
    assert (
        strong.regime_scores["unconfirmed_move_up"]
        < weak.regime_scores["unconfirmed_move_up"]
    )


def test_up_and_down_evidence_mirror_each_other():
    up, _ = _assessment(price=0.03, volume=0.01, oi=0.02, funding=0.0001)
    down, _ = _assessment(price=-0.03, volume=0.01, oi=0.02, funding=0.0001)
    for name in REGIMES:
        if name.endswith("_up"):
            opposite = name[:-3] + "_down"
            assert up.regime_scores[name] == pytest.approx(down.regime_scores[opposite], abs=1e-6)
        elif name.endswith("_down"):
            continue
        else:
            assert up.regime_scores[name] == pytest.approx(down.regime_scores[name], abs=1e-6)


def test_label_stays_argmax_when_volume_is_missing():
    # Missing volume degrades confidence but does not make price/OI
    # unidentifiable, so the rule label must still lead the distribution.
    asset = AssetSnapshot(
        symbol="BTC",
        price_change_1h=0.003,
        spot_volume_change_1h=None,
        funding_rate=0.0,
        open_interest_change_interval=0.0,
    )
    assessment = assess_market(asset)
    assert assessment.regime == "unconfirmed_move_up"
    assert assessment.regime_scores["unconfirmed_move_up"] == max(
        assessment.regime_scores.values()
    )


def test_label_is_argmax_across_the_evidence_grid():
    for price in (-0.03, -0.005, -0.001, 0.0, 0.001, 0.003, 0.005, 0.03):
        for volume in (None, -0.5, 0.0, 0.1, 0.9):
            for oi in (-0.03, -0.001, 0.0, 0.001, 0.03):
                for ratio in (None, 2.5):
                    for seconds in (None, 60.0):
                        asset = AssetSnapshot(
                            symbol="BTC",
                            price_change_1h=price,
                            spot_volume_change_1h=volume,
                            spot_volume_ratio_6h=ratio,
                            funding_rate=0.00013 if price > 0 else -0.00013,
                            open_interest_change_interval=oi,
                            open_interest_interval_seconds=seconds,
                        )
                        assessment = assess_market(asset)
                        assert assessment.regime == max(
                            assessment.regime_scores,
                            key=assessment.regime_scores.get,
                        ), (price, volume, oi, ratio, seconds, assessment.regime)


def test_missing_open_interest_is_called_out_as_insufficient():
    asset = AssetSnapshot(symbol="BTC", price_change_1h=0.04, spot_volume_change_1h=0.09)
    assessment = assess_market(asset)
    assert assessment.regime == "insufficient_data"
    assert assessment.regime_scores["insufficient_data"] == max(assessment.regime_scores.values())


def test_stale_sources_reduce_confidence_and_raise_insufficient_mass():
    fresh = MarketSnapshot(
        as_of="2026-10-17T00:00:00Z", sources=["test"],
        assets=[AssetSnapshot(
            symbol="BTC", price_change_1h=0.03, spot_volume_change_1h=0.01,
            funding_rate=0.0001, open_interest_change_interval=0.02,
        )],
        source_times={"coinbase:BTC": "2026-10-17T00:00:00Z", "deribit:BTC": "2026-10-17T00:00:00Z"},
    )
    stale = fresh.model_copy(update={
        "source_times": {
            "coinbase:BTC": "2026-10-16T22:00:00Z",
            "deribit:BTC": "2026-10-16T22:00:00Z",
        }
    })
    fresh_judgment = RuleBasedObserver().judge(build_state_frame(fresh, fresh.assets[0]))
    stale_judgment = RuleBasedObserver().judge(build_state_frame(stale, stale.assets[0]))
    assert stale_judgment.probabilities["insufficient_data"] > fresh_judgment.probabilities["insufficient_data"]
    assert stale_judgment.confidence < fresh_judgment.confidence


def test_interval_open_interest_change_is_compared_per_hour():
    fast, _ = _assessment(price=0.03, volume=0.01, oi=0.001, seconds=60)
    slow, _ = _assessment(price=0.03, volume=0.01, oi=0.001, seconds=300)
    assert fast.leverage_change == "expanding"
    assert slow.leverage_change == "stable"


def test_confidence_is_bounded_and_discounted_for_conflicts():
    conflicting_assessment, conflicting_asset = _assessment(price=0.0005, volume=0.10, oi=0.0)
    decisive_assessment, decisive_asset = _assessment(price=0.06, volume=0.0, oi=0.05)
    assert conflicting_assessment.alignment == "conflicting"
    assert decisive_assessment.alignment != "conflicting"

    def confidence(asset):
        snapshot = MarketSnapshot(
            as_of="2026-10-17T00:00:00Z", sources=["test"], assets=[asset],
        )
        return RuleBasedObserver().judge(build_state_frame(snapshot, asset)).confidence

    assert 0.05 <= confidence(conflicting_asset) <= 0.85
    assert 0.05 <= confidence(decisive_asset) <= 0.85
    assert confidence(conflicting_asset) < confidence(decisive_asset)
