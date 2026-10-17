import json
import time
from datetime import datetime, timezone
from hashlib import sha256
from statistics import median
from typing import Dict, Optional

import httpx

from .schemas import AssetSnapshot, MarketSnapshot


COINBASE_API = "https://api.exchange.coinbase.com"
DERIBIT_API = "https://www.deribit.com/api/v2"
REQUEST_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 0.2

# Coinbase can still revise the newest hourly candle for a few minutes after
# its nominal close (observed on 2026-10-17: close and volume changed after
# 04:00). Treating that candle as final produced a one-frame price/volume
# spike. Wait for the bucket to settle before using it as history.
CANDLE_SETTLEMENT_SECONDS = 300


def load_live_snapshot(
    timeout: float = 8.0,
    client: Optional[httpx.Client] = None,
    now: Optional[datetime] = None,
) -> MarketSnapshot:
    """Fetch a small public BTC/ETH snapshot without storing credentials or state."""
    owns_client = client is None
    client = client or httpx.Client(timeout=timeout)
    collection_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        assets = []
        source_times = {}
        payload_hashes = {}
        data_errors = {}
        for symbol in ("BTC", "ETH"):
            try:
                candles = _get_json(client, "{}/products/{}-USD/candles".format(COINBASE_API, symbol), {"granularity": 3600})
                asset, metadata = _asset_from_sources(client, symbol, candles, collection_time)
            except ValueError as exc:
                # One asset's outage must not take down the other asset's frame.
                data_errors[symbol] = str(exc)
                continue
            assets.append(asset)
            source_times.update(metadata["source_times"])
            payload_hashes.update(metadata["payload_hashes"])
        if not assets:
            raise ValueError(
                "Market data request failed for every asset: {}".format(
                    "; ".join("{}: {}".format(symbol, message) for symbol, message in data_errors.items())
                )
            )
        received_time = _format_time(collection_time) if now is not None else _now()
        # The frame's knowledge time must not precede any source timestamp.
        # Exchange clocks can be a second ahead of ours; taking the maximum
        # keeps the point-in-time contract true without hiding the skew in the
        # source metadata.
        as_of = max([received_time] + list(source_times.values()))
        return MarketSnapshot(
            as_of=as_of,
            sources=["Coinbase", "Deribit"],
            assets=assets,
            source_times=source_times,
            payload_hashes=payload_hashes,
            available_time=as_of,
            received_time=received_time,
            data_errors=data_errors,
        )
    finally:
        if owns_client:
            client.close()


def _asset_from_sources(
    client: httpx.Client,
    symbol: str,
    candles: object,
    now: datetime,
) -> tuple[AssetSnapshot, dict]:
    if not isinstance(candles, list) or len(candles) < 7:
        raise ValueError("Coinbase returned fewer than seven hourly candles for {}".format(symbol))
    ordered = sorted(candles, key=lambda candle: float(candle[0]))
    completed = [
        candle
        for candle in ordered
        if float(candle[0]) + 3600 + CANDLE_SETTLEMENT_SECONDS <= now.timestamp()
    ]
    if len(completed) < 7:
        raise ValueError("Coinbase returned insufficient completed candles for {}".format(symbol))
    window = completed[-7:]
    _validate_hourly_continuity(window, symbol)
    previous, latest, six_hours_ago = window[-2], window[-1], window[0]
    try:
        previous_close = float(previous[4])
        latest_close = float(latest[4])
        previous_volume = float(previous[5])
        latest_volume = float(latest[5])
        six_hour_close = float(six_hours_ago[4])
        closes = [float(candle[4]) for candle in window]
        volumes = [float(candle[5]) for candle in window]
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError("Unexpected Coinbase candle format for {}".format(symbol)) from exc
    if previous_close == 0 or previous_volume == 0 or six_hour_close == 0:
        raise ValueError("Coinbase returned zero baseline for {}".format(symbol))
    ticker = _get_json(client, "{}/public/ticker".format(DERIBIT_API), {"instrument_name": "{}-PERPETUAL".format(symbol)})
    asset = AssetSnapshot(
        symbol=symbol,
        spot_price=latest_close,
        price_change_1h=(latest_close - previous_close) / previous_close,
        price_change_6h=(latest_close - six_hour_close) / six_hour_close,
        realized_volatility_6h=_realized_volatility(closes),
        spot_volume_change_1h=(latest_volume - previous_volume) / previous_volume,
        spot_volume_ratio_6h=(latest_volume / median(volumes[:-1])) if median(volumes[:-1]) else None,
        funding_rate=_deribit_value(ticker, symbol, "current_funding", "funding_8h"),
        open_interest=_deribit_value(ticker, symbol, "open_interest"),
        open_interest_change_1h=None,
    )
    ticker_result = ticker.get("result", {}) if isinstance(ticker, dict) else {}
    metadata = {
        "source_times": {
            "coinbase:{}".format(symbol): _epoch_iso(float(latest[0]) + 3600),
            "deribit:{}".format(symbol): _epoch_iso(float(ticker_result["timestamp"]) / 1000)
            if ticker_result.get("timestamp") is not None else _now(),
        },
        "payload_hashes": {
            "coinbase:{}".format(symbol): _payload_hash(candles),
            "deribit:{}".format(symbol): _payload_hash(ticker),
        },
    }
    return asset, metadata


def _deribit_value(payload: object, symbol: str, *fields: str) -> Optional[float]:
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
        raise ValueError("Deribit response has no result for {}".format(symbol))
    result = payload["result"]
    for field in fields:
        value = result.get(field)
        if value is not None:
            return float(value)
    return None


class RollingLiveLoader:
    """Add real interval OI changes using only in-process previous samples.

    A change is only meaningful when the previous sample is recent. After a
    restart, the ledger can restore an OI value from hours ago; comparing it
    with the current value would produce a multi-hour change that is then
    mistaken for a short-interval move. ``max_sample_gap_seconds`` prevents
    that by leaving the change missing when the gap is too large.
    """

    def __init__(
        self,
        timeout: float = 8.0,
        previous_open_interest: Optional[Dict[str, float]] = None,
        previous_sampled_at: Optional[Dict[str, str]] = None,
        max_sample_gap_seconds: float = 900.0,
    ):
        self.timeout = timeout
        self.previous_open_interest: Dict[str, float] = previous_open_interest or {}
        self.previous_sampled_at: Dict[str, str] = previous_sampled_at or {}
        self.max_sample_gap_seconds = max_sample_gap_seconds

    def __call__(self) -> MarketSnapshot:
        snapshot = load_live_snapshot(timeout=self.timeout)
        now = _parse_time(snapshot.as_of)
        enriched = []
        for asset in snapshot.assets:
            previous = self.previous_open_interest.get(asset.symbol)
            previous_at = self.previous_sampled_at.get(asset.symbol)
            current = asset.open_interest
            change = None
            elapsed = None
            if previous is not None and current is not None and previous != 0:
                if previous_at is not None:
                    elapsed = (now - _parse_time(previous_at)).total_seconds()
                if elapsed is None or 0 <= elapsed <= self.max_sample_gap_seconds:
                    change = (current - previous) / previous
            if current is not None:
                self.previous_open_interest[asset.symbol] = current
                self.previous_sampled_at[asset.symbol] = snapshot.as_of
            enriched.append(asset.model_copy(update={
                "open_interest_change_interval": change,
                # The sampling gap is part of the measurement: a 0.01% change
                # over 60 seconds and over 5 minutes are not the same signal.
                "open_interest_interval_seconds": elapsed if change is not None else None,
            }))
        return snapshot.model_copy(update={"assets": enriched})


def _get_json(client: httpx.Client, url: str, params: Dict[str, object]) -> object:
    last_error = None
    for attempt in range(REQUEST_ATTEMPTS):
        try:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < REQUEST_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise ValueError("Market data request failed after {} attempts: {}".format(
        REQUEST_ATTEMPTS, url
    )) from last_error


def _payload_hash(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(canonical.encode()).hexdigest()


def _epoch_iso(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_hourly_continuity(candles: list, symbol: str) -> None:
    timestamps = [float(candle[0]) for candle in candles]
    if any(right - left != 3600 for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError("Coinbase returned non-contiguous hourly candles for {}".format(symbol))


def _realized_volatility(closes: list[float]) -> Optional[float]:
    if len(closes) < 3:
        return None
    returns = [current / previous - 1 for previous, current in zip(closes, closes[1:]) if previous]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    return (sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)) ** 0.5


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_time(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
