import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Union

import httpx

from .schemas import AssetSnapshot, MarketSnapshot


DEFAULT_FIXTURE = Path(__file__).parent / "fixtures" / "demo_snapshot.json"
SCENARIO_FIXTURES = {
    "default": DEFAULT_FIXTURE,
    "leverage": Path(__file__).parent / "fixtures" / "demo_leverage_led.json",
    "spot": Path(__file__).parent / "fixtures" / "demo_spot_confirmed.json",
}


def load_fixture(path: Union[str, Path] = DEFAULT_FIXTURE) -> MarketSnapshot:
    fixture_path = Path(path)
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("Fixture file not found: %s" % fixture_path) from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Fixture is not valid JSON: %s" % fixture_path) from exc
    return MarketSnapshot.model_validate(payload)


COINBASE_API = "https://api.exchange.coinbase.com"
DERIBIT_API = "https://www.deribit.com/api/v2"


def load_live_snapshot(timeout: float = 8.0, client: Optional[httpx.Client] = None) -> MarketSnapshot:
    """Fetch a small public snapshot without storing credentials or state.

    Coinbase candles provide one-hour price and spot-volume changes. Deribit
    provides the current funding rate; open-interest change needs a baseline,
    so it remains explicitly missing until the project adds local history.
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        assets = []
        as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        for symbol in ("BTC", "ETH"):
            product = "{}-USD".format(symbol)
            candles = _get_json(client, "{}/products/{}/candles".format(COINBASE_API, product), {
                "granularity": 3600,
            })
            asset = _asset_from_coinbase_and_deribit(client, symbol, candles)
            assets.append(asset)
        return MarketSnapshot(as_of=as_of, sources=["Coinbase", "Deribit"], assets=assets)
    finally:
        if owns_client:
            client.close()


def _asset_from_coinbase_and_deribit(
    client: httpx.Client, symbol: str, candles: object
) -> AssetSnapshot:
    if not isinstance(candles, list) or len(candles) < 8:
        raise ValueError("Coinbase returned fewer than eight hourly candles for {}".format(symbol))
    ordered = sorted(candles, key=lambda candle: candle[0])
    # Coinbase includes the currently forming candle. Use completed candles so
    # repeated runs within the same hour compare stable, like-for-like windows.
    completed = ordered[:-1]
    if len(completed) < 7:
        raise ValueError("Coinbase returned insufficient completed candles for {}".format(symbol))
    latest = completed[-1]
    previous = completed[-2]
    six_hours_ago = completed[-7]
    try:
        previous_close = float(previous[4])
        latest_close = float(latest[4])
        previous_volume = float(previous[5])
        latest_volume = float(latest[5])
        six_hour_close = float(six_hours_ago[4])
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError("Unexpected Coinbase candle format for {}".format(symbol)) from exc
    if previous_close == 0 or previous_volume == 0 or six_hour_close == 0:
        raise ValueError("Coinbase returned zero baseline for {}".format(symbol))

    ticker = _get_json(client, "{}/public/ticker".format(DERIBIT_API), {
        "instrument_name": "{}-PERPETUAL".format(symbol),
    })
    funding_rate = _deribit_funding(ticker, symbol)
    return AssetSnapshot(
        symbol=symbol,
        price_change_1h=(latest_close - previous_close) / previous_close,
        price_change_6h=(latest_close - six_hour_close) / six_hour_close,
        spot_volume_change_1h=(latest_volume - previous_volume) / previous_volume,
        funding_rate=funding_rate,
        open_interest_change_1h=None,
    )


def _deribit_funding(payload: object, symbol: str) -> Optional[float]:
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Deribit response for {}".format(symbol))
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("Deribit response has no result for {}".format(symbol))
    value = result.get("current_funding")
    if value is None:
        value = result.get("funding_8h")
    return None if value is None else float(value)


def _get_json(client: httpx.Client, url: str, params: Dict[str, object]) -> object:
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ValueError("Market data request failed: {}".format(url)) from exc
