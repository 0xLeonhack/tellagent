from tellagent.metrics import analyze_asset
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
