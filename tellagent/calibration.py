from datetime import datetime
from statistics import median
from typing import Dict, Iterable, Optional

from .assessment import hourly_open_interest_change
from .schemas import AssetSnapshot, FeatureBaseline, FrameLedgerRecord


FEATURES = (
    "price_change_1h",
    "spot_volume_change_1h",
    "funding_rate",
    "open_interest_change_interval",
)
MIN_BASELINE_COVERAGE_SECONDS = 23 * 3600


def compute_feature_baselines(
    current: AssetSnapshot,
    records: Iterable[FrameLedgerRecord],
    min_samples: int = 24,
    min_coverage_seconds: int = MIN_BASELINE_COVERAGE_SECONDS,
) -> Dict[str, FeatureBaseline]:
    records = list(records)
    return {
        feature: _baseline(
            _historical_observations(records, current.symbol, feature),
            hourly_open_interest_change(current)
            if feature == "open_interest_change_interval"
            else getattr(current, feature),
            min_samples,
            min_coverage_seconds,
        )
        for feature in FEATURES
    }


def build_strategy_thresholds(baselines: Dict[str, FeatureBaseline]) -> Dict[str, float]:
    """Create bounded adaptive thresholds only from sufficiently covered baselines."""
    thresholds = {}
    mappings = {
        "price_change_1h": ("price_change_1h", 0.005, 0.05),
        "spot_volume_change_1h": ("spot_volume_change_1h", 0.02, 2.0),
        "open_interest_change_interval": ("oi_interval", 0.0025, 0.05),
        "funding_rate": ("funding_extreme", 0.00005, 0.001),
    }
    for feature, (name, lower, upper) in mappings.items():
        baseline = baselines.get(feature)
        if baseline and baseline.ready and baseline.p90_abs is not None:
            thresholds[name] = min(upper, max(lower, baseline.p90_abs))
    return thresholds


def _historical_observations(
    records: list[FrameLedgerRecord], symbol: str, feature: str
) -> list[tuple[datetime, float]]:
    observations = []
    seen = set()
    for record in records:
        if record.asset_snapshot.symbol.upper() != symbol.upper():
            continue
        source_key = _source_key(record, feature, symbol)
        if source_key in seen:
            continue
        seen.add(source_key)
        if feature == "open_interest_change_interval":
            value = hourly_open_interest_change(record.asset_snapshot)
        else:
            value = getattr(record.asset_snapshot, feature)
        if value is not None:
            try:
                observed_at = _parse_time(source_key)
            except ValueError:
                observed_at = _parse_time(record.frame.as_of)
            observations.append((observed_at, value))
    return observations


def _source_key(record: FrameLedgerRecord, feature: str, symbol: str) -> str:
    if feature in {"price_change_1h", "spot_volume_change_1h"}:
        return record.source_times.get("coinbase:{}".format(symbol), record.frame.as_of)
    if feature == "funding_rate":
        return record.source_times.get("deribit:{}".format(symbol), record.frame.as_of)
    return record.frame.as_of


def _baseline(
    observations: list[tuple[datetime, float]],
    current: Optional[float],
    min_samples: int,
    min_coverage_seconds: int,
) -> FeatureBaseline:
    if not observations:
        return FeatureBaseline(sample_count=0, ready=False)
    observations = sorted(observations, key=lambda item: item[0])
    values = [value for _, value in observations]
    observed_from = observations[0][0]
    observed_to = observations[-1][0]
    coverage_seconds = max(0, int((observed_to - observed_from).total_seconds()))
    center = median(values)
    deviations = [abs(value - center) for value in values]
    mad = median(deviations)
    percentile = None
    robust_zscore = None
    if current is not None:
        percentile = sum(value <= current for value in values) / len(values)
        if mad > 0:
            robust_zscore = 0.6745 * (current - center) / mad
    ordered_abs = sorted(abs(value) for value in values)
    index = min(len(ordered_abs) - 1, int(0.9 * (len(ordered_abs) - 1)))
    return FeatureBaseline(
        sample_count=len(values),
        ready=len(values) >= min_samples and coverage_seconds >= min_coverage_seconds,
        coverage_seconds=coverage_seconds,
        observed_from=_format_time(observed_from),
        observed_to=_format_time(observed_to),
        median=center,
        mad=mad,
        percentile=percentile,
        robust_zscore=robust_zscore,
        p90_abs=ordered_abs[index],
    )


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
