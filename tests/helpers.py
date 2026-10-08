from tellagent.schemas import AssetSnapshot, MarketSnapshot


def market_snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        as_of="2026-10-08T00:00:00Z",
        sources=["Coinbase", "Deribit"],
        assets=[
            AssetSnapshot(
                symbol="BTC", price_change_1h=0.028, price_change_6h=0.041,
                spot_volume_change_1h=0.031, funding_rate=0.00018,
                open_interest_change_1h=0.096,
            ),
            AssetSnapshot(
                symbol="ETH", price_change_1h=0.042, price_change_6h=0.067,
                spot_volume_change_1h=0.012, funding_rate=0.00024,
                open_interest_change_1h=0.11,
            ),
        ],
    )
