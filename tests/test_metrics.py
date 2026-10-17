from tellagent.metrics import analysis_fields, analyze_asset, build_deterministic_report
from tellagent.schemas import AssetSnapshot, MarketSnapshot


def test_leverage_expansion_up_scene():
    result = analyze_asset(AssetSnapshot(
        symbol="ETH",
        price_change_1h=0.042,
        spot_volume_change_1h=0.012,
        funding_rate=0.00024,
        open_interest_change_1h=0.11,
    ))
    assert result.suggested_state == "leverage_expansion_up"
    assert result.evidence.supporting
    assert result.evidence.contradicting
    assert any("open interest" in item for item in result.evidence.supporting)
    assert any("现货成交没有同步" in item for item in result.evidence.contradicting)


def test_missing_inputs_are_visible():
    result = analyze_asset(AssetSnapshot(symbol="BTC", price_change_1h=0.01))
    assert result.suggested_state == "insufficient_data"
    assert result.evidence.missing


def test_spot_confirmed_scene():
    result = analyze_asset(AssetSnapshot(
        symbol="BTC",
        price_change_1h=0.028,
        spot_volume_change_1h=0.09,
        spot_volume_ratio_6h=2.0,
        funding_rate=0.00008,
        open_interest_change_1h=0.04,
    ))
    assert result.suggested_state == "spot_confirmed_up"
    assert all("funding rate" not in item for item in result.evidence.supporting)


def test_high_funding_is_counter_evidence_for_spot_confirmation():
    result = analyze_asset(AssetSnapshot(
        symbol="BTC",
        price_change_1h=0.028,
        price_change_6h=0.04,
        spot_volume_change_1h=0.09,
        spot_volume_ratio_6h=2.0,
        funding_rate=0.0003,
        open_interest_change_1h=0.04,
    ))
    assert result.suggested_state == "spot_confirmed_up"
    assert any("funding" in item for item in result.evidence.contradicting)


def test_spot_confirmation_requires_oi_data():
    result = analyze_asset(AssetSnapshot(
        symbol="BTC",
        price_change_1h=0.028,
        spot_volume_change_1h=0.09,
        spot_volume_ratio_6h=2.0,
        funding_rate=0.00008,
    ))
    assert result.suggested_state == "insufficient_data"
    assert any("open interest" in item for item in result.evidence.missing)


def test_spot_confirmation_rejects_large_negative_oi_change():
    result = analyze_asset(AssetSnapshot(
        symbol="BTC",
        price_change_1h=0.03,
        price_change_6h=0.05,
        spot_volume_change_1h=0.08,
        funding_rate=0.00008,
        open_interest_change_1h=-0.20,
    ))
    assert result.suggested_state == "position_unwind_up"


def test_confidence_is_rounded_for_json_output():
    result = analyze_asset(AssetSnapshot(
        symbol="ETH",
        price_change_1h=0.042,
        price_change_6h=0.067,
        spot_volume_change_1h=0.012,
        funding_rate=0.00024,
        open_interest_change_1h=0.11,
    ))
    assert analysis_fields(result)[2] == 0.6


def test_deterministic_report_uses_computed_fields_and_snapshot_metadata():
    asset = AssetSnapshot(
        symbol="ETH",
        price_change_1h=0.042,
        price_change_6h=0.067,
        spot_volume_change_1h=0.012,
        funding_rate=0.00024,
        open_interest_change_1h=0.11,
    )
    snapshot = MarketSnapshot(as_of="2026-10-08T00:00:00Z", sources=["Coinbase", "Deribit"], assets=[asset])
    report = build_deterministic_report(snapshot, asset)
    assert report.asset == "ETH"
    assert report.state == "leverage_expansion_up"
    assert report.data_time == snapshot.as_of
    assert report.sources == snapshot.sources
    assert report.supporting_evidence
    assert report.contradicting_evidence
    assert report.invalidation_condition
