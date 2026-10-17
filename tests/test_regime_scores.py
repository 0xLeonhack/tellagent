from tellagent.assessment import assess_market
from tellagent.schemas import AssetSnapshot


def test_mixed_participation_keeps_secondary_regime_scores():
    assessment = assess_market(AssetSnapshot(
        symbol="BTC", price_change_1h=0.04, spot_volume_change_1h=0.09,
        funding_rate=0.0003, open_interest_change_interval=0.03,
    ))
    assert assessment.regime == "broad_participation_up"
    assert assessment.primary_regime == "broad_participation_up"
    assert assessment.regime_scores["leverage_expansion_up"] > 0
    assert sum(assessment.regime_scores.values()) > 0


def test_quiet_has_no_conflicting_secondary_regime():
    assessment = assess_market(AssetSnapshot(
        symbol="BTC", price_change_1h=0.0001, spot_volume_change_1h=0.0,
        funding_rate=0.0, open_interest_change_interval=0.0,
    ))
    assert assessment.regime == "quiet"
    assert assessment.secondary_regimes == []
