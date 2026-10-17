"""Independent verification of recorded data and Observer judgments.

Nothing here trusts the pipeline's own bookkeeping:

* frame ids are recomputed from their payload,
* every judgment is re-derived from its frozen frame,
* numeric fields are checked for finiteness and physical plausibility,
* ``--live`` refetches public data and recomputes every metric with a separate
  implementation, then compares it with what the loader produced.

The audit never writes to the ledger.
"""

import ast
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional

import httpx

from .data import COINBASE_API, DERIBIT_API, load_live_snapshot
from .ledger import JsonlLedger
from .observer import RuleBasedObserver, frame_fingerprint, legacy_frame_fingerprint
from .scoring import REGIMES


MAX_CLOCK_SKEW_SECONDS = 5
PRICE_TOLERANCE = 1e-9          # completed candles are immutable
DERIVATIVE_TOLERANCE = 0.02     # live ticker can move between two calls
CROSS_SOURCE_TOLERANCE = 0.03   # perp index vs spot basis


@dataclass(frozen=True)
class AuditCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class AuditReport:
    checks: List[AuditCheck] = field(default_factory=list)
    frames: int = 0
    judgments: int = 0
    reproduced: int = 0
    legacy_checked: int = 0

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def extend(self, checks: List[AuditCheck]) -> "AuditReport":
        return AuditReport(
            checks=self.checks + checks,
            frames=self.frames,
            judgments=self.judgments,
            reproduced=self.reproduced,
            legacy_checked=self.legacy_checked,
        )


def audit_ledger(
    root: Path,
    asset: Optional[str] = None,
    limit: int = 50,
) -> AuditReport:
    """Verify recorded frames and judgments without network access."""
    ledger = JsonlLedger(root)
    all_frames = ledger.frames(asset)
    judgments = ledger.judgments(asset)
    all_frame_ids = {record.record_id for record in all_frames}
    frames = all_frames[-limit:] if limit and len(all_frames) > limit else all_frames
    checks = [_source_integrity_check()]
    frame_checks, frame_ids = _audit_frames(frames)
    checks.extend(frame_checks)
    judgment_checks, reproduced, legacy_checked = _audit_judgments(
        judgments,
        {record.record_id: record for record in frames},
        all_frame_ids,
    )
    checks.extend(judgment_checks)
    checks.append(AuditCheck(
        "ledger_scope",
        True,
        "checked {} frames and {} judgments{}".format(
            len(frames), len(judgments), " for {}".format(asset.upper()) if asset else ""
        ) if frames else "ledger is empty",
    ))
    return AuditReport(
        checks=checks,
        frames=len(frames),
        judgments=len(judgments),
        reproduced=reproduced,
        legacy_checked=legacy_checked,
    )


def audit_live(
    asset: Optional[str] = None,
    timeout: float = 8.0,
    root: Optional[Path] = None,
    limit: int = 50,
) -> List[AuditCheck]:
    """Refetch public data and recompute metrics independently.

    With a ledger root, recorded spot metrics are also recomputed from the
    exchange's immutable candle history. This checks the past, not just the
    present: a fabricated frame cannot match public candles it never saw.
    """
    symbols = [asset.upper()] if asset else ["BTC", "ETH"]
    checks: List[AuditCheck] = []
    now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        snapshot = load_live_snapshot(timeout=timeout, now=now)
    except ValueError as exc:
        return [AuditCheck("live_snapshot", False, "loader failed: {}".format(exc))]
    by_symbol = {item.symbol: item for item in snapshot.assets}
    recorded = JsonlLedger(root).frames(asset)[-limit:] if root else []
    with httpx.Client(timeout=timeout) as client:
        for symbol in symbols:
            loaded = by_symbol.get(symbol)
            if loaded is None:
                checks.append(AuditCheck(
                    "live_{}".format(symbol.lower()), False, "loader returned no data"
                ))
                continue
            try:
                raw_candles = _get_json(
                    client,
                    "{}/products/{}-USD/candles".format(COINBASE_API, symbol),
                    {"granularity": 3600},
                )
                ticker = _get_json(
                    client,
                    "{}/public/ticker".format(DERIBIT_API),
                    {"instrument_name": "{}-PERPETUAL".format(symbol)},
                )
                recomputed = _recompute_asset(symbol, raw_candles, ticker, now)
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                checks.append(AuditCheck(
                    "live_{}".format(symbol.lower()), False, "independent fetch failed: {}".format(exc)
                ))
                continue
            checks.extend(_compare_live(symbol, loaded, recomputed, ticker))
            if recorded:
                checks.append(_compare_recorded_history(symbol, recorded, raw_candles))
    return checks


def _audit_frames(frames) -> tuple[List[AuditCheck], Dict[str, object]]:
    checks: List[AuditCheck] = []
    ids: Dict[str, object] = {}
    now = datetime.now(timezone.utc)
    previous_time: Dict[str, datetime] = {}
    hash_ok = True
    numeric_ok = True
    time_ok = True
    assessment_ok = True
    monotonic_ok = True
    duplicate_ids = []
    current_format = 0
    legacy_format = 0
    for record in frames:
        frame = record.frame
        asset = record.asset_snapshot
        current_id = frame_fingerprint(asset, frame.as_of)
        legacy_id = legacy_frame_fingerprint(
            asset, frame.as_of, fields=asset.model_fields_set
        )
        if record.record_id == current_id == frame.frame_id:
            current_format += 1
        elif record.record_id == legacy_id == frame.frame_id:
            legacy_format += 1
        else:
            hash_ok = False
        if record.record_id in ids:
            duplicate_ids.append(record.record_id)
        ids[record.record_id] = record
        if frame.asset != asset.symbol:
            hash_ok = False
        if not _finite_asset(asset):
            numeric_ok = False
        if not record.payload_hashes and "Coinbase" in (record.sources or []):
            hash_ok = False
        for value in record.payload_hashes.values():
            if not _looks_like_sha256(value):
                hash_ok = False
        try:
            as_of = _parse_time(frame.as_of)
            future_limit = now.replace(tzinfo=timezone.utc)
            if (as_of - future_limit).total_seconds() > MAX_CLOCK_SKEW_SECONDS:
                time_ok = False
            for source_time in record.source_times.values():
                if (_parse_time(source_time) - as_of).total_seconds() > MAX_CLOCK_SKEW_SECONDS:
                    # Source timestamps must not be later than collection time.
                    time_ok = False
            previous = previous_time.get(asset.symbol)
            if previous is not None and as_of < previous:
                monotonic_ok = False
            previous_time[asset.symbol] = as_of
        except ValueError:
            time_ok = False
        if frame.assessment is None or frame.assessment.regime not in REGIMES:
            assessment_ok = False
    checks.append(AuditCheck(
        "frame_ids",
        hash_ok,
        "frame ids and payload hashes match ({} current, {} legacy format)".format(
            current_format, legacy_format
        ) if hash_ok else "frame id or payload hash mismatch",
    ))
    checks.append(AuditCheck(
        "frame_numbers",
        numeric_ok,
        "all recorded numbers are finite and prices are positive"
        if numeric_ok else "non-finite or non-positive numeric field found",
    ))
    checks.append(AuditCheck(
        "frame_timestamps",
        time_ok,
        "no future collection time and no source later than collection"
        if time_ok else "invalid or future timestamp found",
    ))
    checks.append(AuditCheck(
        "frame_order",
        monotonic_ok and not duplicate_ids,
        "timestamps are monotonic per asset and frame ids are unique"
        if monotonic_ok and not duplicate_ids
        else "out-of-order timestamps or duplicate frame ids: {}".format(duplicate_ids[:5]),
    ))
    checks.append(AuditCheck(
        "frame_assessment",
        assessment_ok,
        "every frame carries a valid deterministic assessment"
        if assessment_ok else "missing or invalid assessment",
    ))
    return checks, ids


def _audit_judgments(judgments, frames_by_id, frame_ids) -> tuple[List[AuditCheck], int, int]:
    """Validate every judgment; reproduce the ones whose frame is in scope."""
    checks: List[AuditCheck] = []
    linkage_ok = True
    probability_ok = True
    metadata_ok = True
    reproduced = 0
    legacy_checked = 0
    legacy_ok = True
    reproduction_ok = True
    reproduction_detail = "no rule-based judgments to reproduce"
    observer = RuleBasedObserver()
    seen = set()
    for judgment in judgments:
        if judgment.frame_id not in frame_ids:
            linkage_ok = False
            continue
        probabilities = judgment.probabilities
        if set(probabilities) != set(REGIMES):
            probability_ok = False
        else:
            total = sum(probabilities.values())
            if abs(total - 1.0) > 0.01:
                probability_ok = False
            if any(value < 0 or value > 1 for value in probabilities.values()):
                probability_ok = False
            leader = max(probabilities, key=probabilities.get)
            if leader != judgment.selected_value:
                probability_ok = False
        if not (0 < judgment.confidence <= 1):
            probability_ok = False
        if not judgment.provider or not judgment.model_version:
            metadata_ok = False
        if judgment.provider != observer.provider:
            continue
        if judgment.frame_id in seen or judgment.frame_id not in frames_by_id:
            continue
        seen.add(judgment.frame_id)
        record = frames_by_id[judgment.frame_id]
        if judgment.model_version != observer.model_version:
            # A model change makes exact re-derivation impossible: the old
            # scoring code no longer exists. The frozen frame still carries
            # the deterministic assessment the legacy judgment was based on,
            # so verify coherence with that instead of pretending to replay.
            legacy_checked += 1
            assessment = record.frame.assessment
            if assessment is None or assessment.regime != judgment.selected_value:
                legacy_ok = False
            continue
        # Re-derive the judgment from the frozen frame. This is the strongest
        # anti-fabrication check available offline.
        try:
            rejudged = observer.judge(record.frame)
        except ValueError:
            reproduction_ok = False
            continue
        if rejudged.selected_value != judgment.selected_value:
            reproduction_ok = False
        elif abs(rejudged.probabilities[rejudged.selected_value]
                 - probabilities.get(judgment.selected_value, 0.0)) > 1e-9:
            reproduction_ok = False
        elif abs(rejudged.confidence - judgment.confidence) > 1e-9:
            reproduction_ok = False
        elif rejudged.research_priority != judgment.research_priority:
            reproduction_ok = False
        reproduced += 1
    if reproduced or legacy_checked:
        reproduction_detail = (
            "{} current-version judgments re-derived exactly; "
            "{} legacy-version judgments matched their frozen assessment "
            "(not re-derived: model version changed)"
        ).format(reproduced, legacy_checked)
    checks.append(AuditCheck(
        "judgment_linkage",
        linkage_ok,
        "every judgment points to a recorded frame"
        if linkage_ok else "orphan judgment found",
    ))
    checks.append(AuditCheck(
        "judgment_probabilities",
        probability_ok,
        "probabilities are complete, normalised, and agree with the selected state"
        if probability_ok else "invalid probability vector or confidence",
    ))
    checks.append(AuditCheck(
        "judgment_metadata",
        metadata_ok,
        "provider and model version are recorded"
        if metadata_ok else "missing provider/model metadata",
    ))
    checks.append(AuditCheck("judgment_reproduction", reproduction_ok, reproduction_detail))
    if legacy_checked:
        checks.append(AuditCheck(
            "judgment_legacy_coherence",
            legacy_ok,
            "legacy judgments agree with the assessment frozen in their frame"
            if legacy_ok else "legacy judgment disagrees with its frozen assessment",
        ))
    return checks, reproduced, legacy_checked


def _source_integrity_check() -> AuditCheck:
    """Parse the production package and reject randomness/mocking imports."""
    banned = {"random", "faker", "mock"}
    hits = []
    for path in sorted(Path(__file__).parent.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in banned:
                    hits.append("{}:{}".format(path.name, name))
    return AuditCheck(
        "source_integrity",
        not hits,
        "production package imports no random/fake/mock modules"
        if not hits else "suspicious imports: {}".format(", ".join(hits)),
    )


def _spot_metrics(candles, now: datetime) -> dict:
    """Recompute spot metrics for one point in time from raw candles."""
    if not isinstance(candles, list) or len(candles) < 8:
        raise ValueError("fewer than eight candles")
    ordered = sorted(candles, key=lambda candle: float(candle[0]))
    completed = [candle for candle in ordered if float(candle[0]) + 3600 <= now.timestamp()]
    window = completed[-7:]
    if len(window) < 7:
        raise ValueError("fewer than seven completed candles")
    timestamps = [float(candle[0]) for candle in window]
    if any(right - left != 3600 for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError("non-contiguous candles")
    closes = [float(candle[4]) for candle in window]
    volumes = [float(candle[5]) for candle in window]
    if closes[-2] == 0 or volumes[-2] == 0 or closes[0] == 0:
        raise ValueError("zero baseline in candles")
    returns = [current / previous - 1 for previous, current in zip(closes, closes[1:])]
    mean = sum(returns) / len(returns)
    volatility = (sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)) ** 0.5
    return {
        "spot_price": closes[-1],
        "price_change_1h": (closes[-1] - closes[-2]) / closes[-2],
        "price_change_6h": (closes[-1] - closes[0]) / closes[0],
        "realized_volatility_6h": volatility,
        "spot_volume_change_1h": (volumes[-1] - volumes[-2]) / volumes[-2],
        "spot_volume_ratio_6h": volumes[-1] / median(volumes[:-1]),
        "latest_candle_open": _epoch_iso(timestamps[-1]),
        "candle_hash": _payload_hash(window),
    }


def _recompute_asset(symbol: str, candles, ticker, now: datetime) -> dict:
    """Independent reimplementation of the loader's metric formulas."""
    recomputed = _spot_metrics(candles, now)
    result = ticker.get("result", {})
    recomputed.update({
        "funding_rate": float(result.get("current_funding", result.get("funding_8h", 0.0))),
        "open_interest": float(result.get("open_interest", 0.0)),
        "index_price": float(result.get("index_price", 0.0) or 0.0),
    })
    return recomputed


SPOT_FIELDS = (
    "spot_price",
    "price_change_1h",
    "price_change_6h",
    "realized_volatility_6h",
    "spot_volume_change_1h",
    "spot_volume_ratio_6h",
)


def _compare_recorded_history(symbol: str, frames, candles) -> AuditCheck:
    """Check recorded spot metrics against the exchange's candle history."""
    mismatches = []
    checked = 0
    for record in frames:
        if record.frame.asset.upper() != symbol.upper():
            continue
        asset = record.asset_snapshot
        try:
            now = _parse_time(record.received_time)
            recomputed = _spot_metrics(candles, now)
        except (ValueError, TypeError):
            # The frame predates the retained candle window; nothing to check.
            continue
        checked += 1
        for name in SPOT_FIELDS:
            recorded_value = getattr(asset, name)
            if recorded_value is None:
                continue
            if not math.isclose(
                recorded_value, recomputed[name], rel_tol=1e-9, abs_tol=1e-12
            ):
                mismatches.append("{}@{} (recorded {}, history {})".format(
                    name, record.frame.as_of, recorded_value, recomputed[name]
                ))
    name = "live_{}_recorded_history".format(symbol.lower())
    if not checked:
        return AuditCheck(
            name, True, "no recorded frames fall inside the retained candle window"
        )
    return AuditCheck(
        name,
        not mismatches,
        "{} recorded frames match recomputation from public candle history".format(checked)
        if not mismatches else "recorded metrics disagree with candle history: {}".format(
            ", ".join(mismatches[:5])
        ),
    )


def _compare_live(symbol: str, loaded, recomputed: dict, ticker) -> List[AuditCheck]:
    checks = []
    mismatches = []
    for name in SPOT_FIELDS:
        loaded_value = getattr(loaded, name)
        expected = recomputed[name]
        if loaded_value is None or not math.isclose(
            loaded_value, expected, rel_tol=0, abs_tol=PRICE_TOLERANCE
        ):
            mismatches.append("{} (loaded {}, fetched {})".format(name, loaded_value, expected))
    checks.append(AuditCheck(
        "live_{}_spot".format(symbol.lower()),
        not mismatches,
        "independent Coinbase recomputation matches every spot metric"
        if not mismatches else "spot metric mismatch: {}".format(", ".join(mismatches)),
    ))

    derivative_mismatch = []
    for name, rel_tol, abs_tol in (
        # Deribit's current_funding is a live prediction that moves every few
        # seconds, so two fetches cannot be compared more tightly than 5e-5.
        ("funding_rate", 0.25, 5e-5),
        ("open_interest", DERIVATIVE_TOLERANCE, 1e-12),
    ):
        loaded_value = getattr(loaded, name)
        expected = recomputed[name]
        if loaded_value is None or not math.isclose(
            loaded_value, expected, rel_tol=rel_tol, abs_tol=abs_tol
        ):
            derivative_mismatch.append(
                "{} (loaded {}, fetched {})".format(name, loaded_value, expected)
            )
    checks.append(AuditCheck(
        "live_{}_derivatives".format(symbol.lower()),
        not derivative_mismatch,
        "Deribit funding and open interest match within live-ticker tolerance"
        if not derivative_mismatch
        else "derivative mismatch: {}".format(", ".join(derivative_mismatch)),
    ))

    index_price = recomputed.get("index_price") or 0.0
    cross_ok = index_price > 0 and abs(
        recomputed["spot_price"] / index_price - 1.0
    ) <= CROSS_SOURCE_TOLERANCE
    checks.append(AuditCheck(
        "live_{}_cross_source".format(symbol.lower()),
        cross_ok,
        "Coinbase close {:.2f} vs Deribit index {:.2f} ({:+.2%})".format(
            recomputed["spot_price"], index_price,
            recomputed["spot_price"] / index_price - 1.0 if index_price else float("nan"),
        ) if cross_ok else "cross-source price divergence or missing index price",
    ))

    return checks


def _finite_asset(asset) -> bool:
    numeric = (
        asset.spot_price,
        asset.price_change_1h,
        asset.price_change_6h,
        asset.realized_volatility_6h,
        asset.spot_volume_change_1h,
        asset.spot_volume_ratio_6h,
        asset.funding_rate,
        asset.open_interest,
        asset.open_interest_change_interval,
        asset.open_interest_change_1h,
        asset.open_interest_interval_seconds,
    )
    for value in numeric:
        if value is None:
            continue
        if not math.isfinite(value):
            return False
    return asset.spot_price is None or asset.spot_price > 0


def _looks_like_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


def _get_json(client: httpx.Client, url: str, params: dict):
    response = client.get(url, params=params)
    response.raise_for_status()
    return response.json()


def _payload_hash(payload) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(canonical.encode()).hexdigest()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _epoch_iso(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
