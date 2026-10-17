import pytest

from tellagent.metrics import analyze_asset
from tellagent.observer import RuleBasedJevObserver, build_state_frame
from tellagent.assessment import assess_snapshot_quality
from tellagent.schemas import AssetSnapshot, MarketSnapshot


@pytest.mark.parametrize(
    ("price", "volume", "oi", "expected"),
    [
        (-0.03, 0.08, 0.001, "spot_confirmed_down"),
        (0.03, 0.01, -0.03, "position_unwind_up"),
        (-0.03, 0.01, 0.03, "leverage_expansion_down"),
        (0.03, 0.08, 0.03, "broad_participation_up"),
        (-0.03, 0.08, 0.03, "broad_participation_down"),
        (0.0005, 0.0, 0.001, "quiet"),
        (0.0005, 0.08, 0.03, "conflicting"),
        (0.01, 0.0, 0.001, "unconfirmed_move_up"),
        (-0.01, -0.2, 0.001, "unconfirmed_move_down"),
    ],
)
def test_direction_and_driver_matrix(price, volume, oi, expected):
    asset = AssetSnapshot(
        symbol="ETH",
        price_change_1h=price,
        price_change_6h=price,
        spot_volume_change_1h=volume,
        funding_rate=0.0001,
        open_interest_change_interval=oi,
    )
    analysis = analyze_asset(asset)
    assert analysis.suggested_state == expected


def test_leverage_expansion_down_is_escalated():
    asset = AssetSnapshot(
        symbol="ETH", price_change_1h=-0.03, price_change_6h=-0.04,
        spot_volume_change_1h=0.01, funding_rate=-0.0003,
        open_interest_change_interval=0.03,
    )
    snapshot = MarketSnapshot(as_of="2026-10-16T00:00:00Z", sources=["test"], assets=[asset])
    judgment = RuleBasedJevObserver().judge(build_state_frame(snapshot, asset))
    assert judgment.selected_value == "leverage_expansion_down"
    assert judgment.research_priority == "significant"


def test_missing_data_and_quiet_are_distinct():
    missing = analyze_asset(AssetSnapshot(symbol="BTC", price_change_1h=0.0))
    quiet = analyze_asset(AssetSnapshot(
        symbol="BTC", price_change_1h=0.0, price_change_6h=0.0,
        spot_volume_change_1h=0.0, funding_rate=0.0,
        open_interest_change_interval=0.0,
    ))
    assert missing.suggested_state == "insufficient_data"
    assert quiet.suggested_state == "quiet"


def test_source_alignment_quality_degrades_stale_sources():
    asset = AssetSnapshot(symbol="BTC", price_change_1h=0.03, open_interest_change_interval=0.02)
    snapshot = MarketSnapshot(
        as_of="2026-10-16T00:00:00Z",
        sources=["Coinbase", "Deribit"],
        assets=[asset],
        source_times={
            "coinbase:BTC": "2026-10-15T23:00:00Z",
            "deribit:BTC": "2026-10-16T00:00:00Z",
        },
    )
    score, alignment = assess_snapshot_quality(snapshot, asset)
    assert score == 0.25
    assert alignment == 3600
    frame = build_state_frame(snapshot, asset)
    assert frame.assessment.data_quality == "insufficient"
    assert frame.quality_summary["source_alignment_seconds"] == "3600"
