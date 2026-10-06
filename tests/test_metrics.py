from tellagent.metrics import analysis_fields, analyze_asset
from tellagent.schemas import AssetSnapshot


def test_leverage_led_scene():
    result = analyze_asset(AssetSnapshot(
        symbol="ETH",
        price_change_1h=0.042,
        spot_volume_change_1h=0.012,
        funding_rate=0.00024,
        open_interest_change_1h=0.11,
    ))
    assert result.suggested_state == "leverage_led"
    assert result.evidence.supporting
    assert result.evidence.contradicting
    assert any("弱于持仓增长" in item for item in result.evidence.supporting)
    assert any("也增加" in item for item in result.evidence.contradicting)


def test_missing_inputs_are_visible():
    result = analyze_asset(AssetSnapshot(symbol="BTC", price_change_1h=0.01))
    assert result.suggested_state == "uncertain"
    assert result.evidence.missing


def test_spot_confirmed_scene():
    result = analyze_asset(AssetSnapshot(
        symbol="BTC",
        price_change_1h=0.028,
        spot_volume_change_1h=0.09,
        funding_rate=0.00008,
        open_interest_change_1h=0.04,
    ))
    assert result.suggested_state == "spot_confirmed"
    assert all("funding rate" not in item for item in result.evidence.supporting)


def test_high_funding_is_counter_evidence_for_spot_confirmation():
    result = analyze_asset(AssetSnapshot(
        symbol="BTC",
        price_change_1h=0.028,
        price_change_6h=0.04,
        spot_volume_change_1h=0.09,
        funding_rate=0.0003,
        open_interest_change_1h=0.04,
    ))
    assert result.suggested_state == "spot_confirmed"
    assert any("funding rate" in item for item in result.evidence.contradicting)


def test_confidence_is_rounded_for_json_output():
    result = analyze_asset(AssetSnapshot(
        symbol="ETH",
        price_change_1h=0.042,
        price_change_6h=0.067,
        spot_volume_change_1h=0.012,
        funding_rate=0.00024,
        open_interest_change_1h=0.11,
    ))
    assert analysis_fields(result)[2] == 0.83
