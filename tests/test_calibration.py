from tellagent.calibration import build_strategy_thresholds, compute_feature_baselines
from tellagent.metrics import analyze_asset
from tellagent.ledger import JsonlLedger
from tellagent.observer import build_state_frame
from tellagent.schemas import AssetSnapshot, MarketSnapshot


def test_feature_baseline_reports_robust_statistics(tmp_path):
    ledger = JsonlLedger(tmp_path)
    for index in range(24):
        asset = AssetSnapshot(
            symbol="BTC",
            price_change_1h=index / 1000,
            spot_volume_change_1h=index / 100,
            funding_rate=index / 100000,
            open_interest_change_interval=index / 1000,
        )
        as_of = "2026-10-08T{:02d}:00:00Z".format(index)
        snapshot = MarketSnapshot(
            as_of=as_of, sources=["test"], assets=[asset],
            source_times={"coinbase:BTC": as_of, "deribit:BTC": as_of},
        )
        ledger.append_frame(snapshot, asset, build_state_frame(snapshot, asset))

    current = AssetSnapshot(
        symbol="BTC", price_change_1h=0.03, spot_volume_change_1h=0.3,
        funding_rate=0.0003, open_interest_change_interval=0.03,
    )
    baselines = compute_feature_baselines(current, ledger.frames("BTC"))
    assert baselines["price_change_1h"].ready is True
    assert baselines["price_change_1h"].sample_count == 24
    assert baselines["price_change_1h"].percentile == 1.0
    assert baselines["price_change_1h"].robust_zscore is not None
    thresholds = build_strategy_thresholds(baselines)
    assert thresholds["price_change_1h"] == 0.02
    assert thresholds["spot_volume_change_1h"] == 0.2


def test_feature_baseline_is_not_ready_with_low_coverage():
    current = AssetSnapshot(symbol="ETH", price_change_1h=0.03)
    baseline = compute_feature_baselines(current, [], min_samples=24)
    assert baseline["price_change_1h"].ready is False
    assert build_strategy_thresholds(baseline) == {}


def test_asset_uses_ready_calibrated_thresholds():
    asset = AssetSnapshot(
        symbol="ETH", price_change_1h=0.01, spot_volume_change_1h=0.03, spot_volume_ratio_6h=2.0,
        open_interest_change_interval=0.001,
        strategy_thresholds={
            "price_change_1h": 0.005,
            "spot_volume_change_1h": 0.02,
            "oi_interval": 0.005,
        },
    )
    assert analyze_asset(asset).suggested_state == "spot_confirmed_up"
