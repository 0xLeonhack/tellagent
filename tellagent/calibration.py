from statistics import median
from typing import Dict, Iterable, Optional

from .schemas import AssetSnapshot, FeatureBaseline, FrameLedgerRecord


FEATURES = (
    "price_change_1h",
    "spot_volume_change_1h",
    "funding_rate",
    "open_interest_change_interval",
)


def compute_feature_baselines(
    current: AssetSnapshot,
    records: Iterable[FrameLedgerRecord],
    min_samples: int = 24,
) -> Dict[str, FeatureBaseline]:
    records = list(records)
    return {
        feature: _baseline(
            _historical_values(records, current.symbol, feature),
            getattr(current, feature),
            min_samples,
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
    }
    for feature, (name, lower, upper) in mappings.items():
        baseline = baselines.get(feature)
        if baseline and baseline.ready and baseline.p90_abs is not None:
            thresholds[name] = min(upper, max(lower, baseline.p90_abs))
    return thresholds


def _historical_values(
    records: list[FrameLedgerRecord], symbol: str, feature: str
) -> list[float]:
    values = []
    seen = set()
    for record in records:
        if record.asset_snapshot.symbol.upper() != symbol.upper():
            continue
        source_key = _source_key(record, feature, symbol)
        if source_key in seen:
            continue
        seen.add(source_key)
        value = getattr(record.asset_snapshot, feature)
        if value is not None:
            values.append(value)
    return values


def _source_key(record: FrameLedgerRecord, feature: str, symbol: str) -> str:
    if feature in {"price_change_1h", "spot_volume_change_1h"}:
        return record.source_times.get("coinbase:{}".format(symbol), record.frame.as_of)
    if feature == "funding_rate":
        return record.source_times.get("deribit:{}".format(symbol), record.frame.as_of)
    return record.frame.as_of


def _baseline(values: list[float], current: Optional[float], min_samples: int) -> FeatureBaseline:
    if not values:
        return FeatureBaseline(sample_count=0, ready=False)
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
        ready=len(values) >= min_samples,
        median=center,
        mad=mad,
        percentile=percentile,
        robust_zscore=robust_zscore,
        p90_abs=ordered_abs[index],
    )
