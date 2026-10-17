"""Empirical checks behind the scoring thresholds and the Gate.

Two independent measurements:

* ``evaluate_history`` downloads public hourly candles and funding history and
  reports the real distributions that the default thresholds are based on,
  plus simple forward-return information tests.
* ``evaluate_ledger`` measures the live pipeline's score behaviour and compares
  the current Gate with the previous flat-threshold Gate on the same judgments.

Historical open interest is not available from any public endpoint used here,
so full-regime backtesting is impossible. This module never invents it; the
limitation is stated in the generated report.
"""

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Dict, Iterable, List, Optional

import httpx

from .data import COINBASE_API, DERIBIT_API
from .gate import evaluate_gate
from .ledger import JsonlLedger
from .schemas import ContinuousJudgment
from .scoring import (
    DEFAULT_PRICE_THRESHOLD,
    DEFAULT_VOLUME_THRESHOLD,
    FUNDING_EXTREME,
)
from .trends import compute_judgment_trend


@dataclass(frozen=True)
class HistoryRow:
    timestamp: int
    close: float
    volume: float
    funding_8h: Optional[float]
    funding_1h: Optional[float]


@dataclass(frozen=True)
class LegacyDecision:
    action: str


def fetch_history(
    symbol: str,
    days: int = 30,
    client: Optional[httpx.Client] = None,
    now: Optional[datetime] = None,
) -> List[HistoryRow]:
    """Fetch aligned hourly candles and Deribit funding history."""
    owns = client is None
    client = client or httpx.Client(timeout=20.0)
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    try:
        candles = _fetch_candles(client, symbol, days, now)
        funding = _fetch_funding(client, symbol, days, now)
    finally:
        if owns:
            client.close()
    rows = []
    for timestamp, candle in sorted(candles.items()):
        if timestamp + 3600 > now.timestamp():
            continue
        rate = funding.get(timestamp)
        rows.append(HistoryRow(
            timestamp=timestamp,
            close=float(candle[4]),
            volume=float(candle[5]),
            funding_8h=rate[0] if rate else None,
            funding_1h=rate[1] if rate else None,
        ))
    return rows


def summarize_history(
    symbol: str,
    rows: List[HistoryRow],
    price_threshold: float = DEFAULT_PRICE_THRESHOLD,
    volume_threshold: float = DEFAULT_VOLUME_THRESHOLD,
    funding_threshold: float = FUNDING_EXTREME,
) -> dict:
    closes = [row.close for row in rows]
    volumes = [row.volume for row in rows]
    returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]
    volume_changes = [
        volumes[i] / volumes[i - 1] - 1 for i in range(1, len(volumes)) if volumes[i - 1]
    ]
    volume_ratios = []
    for i in range(6, len(volumes)):
        baseline = median(volumes[i - 6:i])
        if baseline:
            volume_ratios.append(volumes[i] / baseline)
    funding = [abs(row.funding_8h) for row in rows if row.funding_8h is not None]

    large = []
    quiet = []
    confirmed = []
    unconfirmed = []
    funding_extreme = []
    funding_neutral = []
    for i in range(6, len(closes) - 8):
        if not closes[i]:
            continue
        move = closes[i] / closes[i - 1] - 1 if closes[i - 1] else 0.0
        forward_1h = closes[i + 1] / closes[i] - 1
        forward_3h = closes[i + 3] / closes[i] - 1
        forward_8h = closes[i + 8] / closes[i] - 1
        baseline = median(volumes[i - 6:i]) or 0.0
        ratio = volumes[i] / baseline if baseline else 0.0
        if abs(move) >= price_threshold:
            large.append((abs(forward_1h), abs(forward_3h), _same_sign(move, forward_3h)))
            if ratio >= 1.5:
                confirmed.append((abs(forward_3h), _same_sign(move, forward_3h)))
            else:
                unconfirmed.append((abs(forward_3h), _same_sign(move, forward_3h)))
        else:
            quiet.append((abs(forward_1h), abs(forward_3h)))
        if rows[i].funding_8h is not None:
            bucket = funding_extreme if abs(rows[i].funding_8h) >= funding_threshold else funding_neutral
            bucket.append(forward_8h)

    return {
        "symbol": symbol,
        "hours": len(rows),
        "price_abs": _percentiles([abs(value) for value in returns]),
        "volume_abs": _percentiles([abs(value) for value in volume_changes]),
        "volume_ratio": _percentiles(volume_ratios),
        "funding_abs": _percentiles(funding),
        "large_move_share": _ratio(len(large), len(large) + len(quiet)),
        "forward_abs_1h_after_large": _mean(first for first, _, _ in large),
        "forward_abs_1h_after_quiet": _mean(first for first, _ in quiet),
        "forward_abs_3h_after_large": _mean(second for _, second, _ in large),
        "forward_abs_3h_after_quiet": _mean(second for _, second in quiet),
        "continuation_after_large": _mean(flag for _, _, flag in large),
        "volume_confirmed_share": _ratio(len(confirmed), len(confirmed) + len(unconfirmed)),
        "forward_abs_3h_confirmed": _mean(value for value, _ in confirmed),
        "forward_abs_3h_unconfirmed": _mean(value for value, _ in unconfirmed),
        "continuation_confirmed": _mean(flag for _, flag in confirmed),
        "continuation_unconfirmed": _mean(flag for _, flag in unconfirmed),
        "funding_extreme_forward_8h": _mean(funding_extreme),
        "funding_neutral_forward_8h": _mean(funding_neutral),
        "funding_extreme_count": len(funding_extreme),
        "suggested": {
            "price_change_1h": _clamp(_percentile([abs(value) for value in returns], 0.90), 0.005, 0.05),
            "spot_volume_change_1h": _clamp(_percentile([abs(value) for value in volume_changes], 0.90), 0.02, 2.0),
            "funding_extreme": _clamp(_percentile(funding, 0.90), 0.00005, 0.001),
        },
        "current": {
            "price_change_1h": price_threshold,
            "spot_volume_change_1h": volume_threshold,
            "funding_extreme": funding_threshold,
        },
    }


def evaluate_ledger(root: Path, asset: Optional[str] = None) -> dict:
    """Measure scores and Gate behaviour on recorded live judgments."""
    ledger = JsonlLedger(root)
    frames = ledger.frames(asset)
    judgments = ledger.judgments(asset)
    by_id = {record.record_id: record for record in frames}
    linked = [
        judgment for judgment in judgments
        if judgment.frame_id in by_id and judgment.provider == "rule-based-observer"
    ]
    linked.sort(key=lambda item: item.as_of)
    states = Counter(judgment.selected_value for judgment in linked)
    entropies = [_entropy(judgment.probabilities) for judgment in linked]
    top_probabilities = [
        judgment.probabilities.get(judgment.selected_value, 0.0) for judgment in linked
    ]
    one_frame_flips = 0
    v1_escalations = 0
    v2_escalations = 0
    v1_false = 0
    v2_false = 0
    suppressed = 0
    suppressed_wrong = 0
    for index, judgment in enumerate(linked):
        history = linked[:index]
        if not history:
            continue
        trend = compute_judgment_trend(judgment, history)
        previous = history[-1]
        old = _gate_v1(judgment, previous, trend)
        new = evaluate_gate(judgment, previous, event_open=False, trend=trend)
        future = linked[index + 1] if index + 1 < len(linked) else None
        if future is not None and future.selected_value != judgment.selected_value:
            one_frame_flips += 1
        if old.action != "silent":
            v1_escalations += 1
            if future is not None and future.selected_value != judgment.selected_value:
                v1_false += 1
        if new.action != "silent":
            v2_escalations += 1
            if future is not None and future.selected_value != judgment.selected_value:
                v2_false += 1
        if old.action != "silent" and new.action == "silent":
            suppressed += 1
            if future is not None and future.selected_value != judgment.selected_value:
                suppressed_wrong += 1
    return {
        "asset": asset.upper() if asset else "ALL",
        "judgments": len(linked),
        "states": dict(states.most_common()),
        "mean_top_probability": _mean(top_probabilities),
        "mean_entropy": _mean(entropies),
        "mean_confidence": _mean([judgment.confidence for judgment in linked]),
        "one_frame_flip_rate": _ratio(one_frame_flips, max(0, len(linked) - 1)),
        "gate_v1_escalations": v1_escalations,
        "gate_v2_escalations": v2_escalations,
        "gate_v1_escalations_not_persisting": v1_false,
        "gate_v2_escalations_not_persisting": v2_false,
        "gate_v1_suppressed_by_v2": suppressed,
        "suppressed_that_did_not_persist": suppressed_wrong,
    }


def _gate_v1(judgment: ContinuousJudgment, previous: ContinuousJudgment, trend):
    """The previous Gate: any state change or 0.2 probability move escalates."""
    delta = round(
        judgment.probabilities.get(judgment.selected_value, 0.0)
        - previous.probabilities.get(judgment.selected_value, 0.0),
        4,
    )
    trend_deltas = [
        value for value in (
            trend.probability_delta_1, trend.probability_delta_3, trend.probability_delta_12
        ) if value is not None
    ]
    largest = max([delta] + trend_deltas, key=abs)
    triggers = []
    if judgment.selected_value != previous.selected_value:
        triggers.append("state_changed")
    if abs(largest) >= 0.2:
        triggers.append("probability_moved")
    if set(judgment.contradicting_roles) != set(previous.contradicting_roles):
        triggers.append("conflicts_changed")
    return LegacyDecision("update_event" if triggers else "silent")


def _fetch_candles(client, symbol: str, days: int, now: datetime) -> Dict[int, list]:
    rows: Dict[int, list] = {}
    cursor = now - timedelta(days=days)
    while cursor < now:
        end = min(cursor + timedelta(days=11), now)
        response = client.get(
            "{}/products/{}-USD/candles".format(COINBASE_API, symbol),
            params={"granularity": 3600, "start": cursor.isoformat(), "end": end.isoformat()},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("Coinbase candle request failed: {}".format(payload))
        for candle in payload:
            rows[int(candle[0])] = candle
        cursor = end
    return rows


def _fetch_funding(client, symbol: str, days: int, now: datetime) -> Dict[int, tuple]:
    response = client.get(
        "{}/public/get_funding_rate_history".format(DERIBIT_API),
        params={
            "instrument_name": "{}-PERPETUAL".format(symbol),
            "start_timestamp": int((now - timedelta(days=days)).timestamp() * 1000),
            "end_timestamp": int(now.timestamp() * 1000),
        },
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload.get("result"), list):
        raise ValueError("Deribit funding request failed: {}".format(payload))
    return {
        int(item["timestamp"] // 1000): (item.get("interest_8h"), item.get("interest_1h"))
        for item in payload["result"]
    }


def _same_sign(left: float, right: float) -> bool:
    return (left > 0) == (right > 0)


def _percentiles(values: Iterable[float]) -> Dict[str, float]:
    values = [value for value in values if math.isfinite(value)]
    return {
        "p50": _percentile(values, 0.50),
        "p75": _percentile(values, 0.75),
        "p90": _percentile(values, 0.90),
        "p95": _percentile(values, 0.95),
        "count": len(values),
    }


def _percentile(values: list, fraction: float) -> Optional[float]:
    ordered = sorted(value for value in values if math.isfinite(value))
    if not ordered:
        return None
    index = min(len(ordered) - 1, int(fraction * (len(ordered) - 1)))
    return ordered[index]


def _mean(values: Iterable[float]) -> Optional[float]:
    values = [value for value in values if value is not None and math.isfinite(value)]
    return mean(values) if values else None


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    return numerator / denominator if denominator else None


def _entropy(probabilities: Dict[str, float]) -> float:
    return -sum(value * math.log(value) for value in probabilities.values() if value > 0)


def _clamp(value: Optional[float], lower: float, upper: float) -> Optional[float]:
    if value is None:
        return None
    return max(lower, min(upper, value))
