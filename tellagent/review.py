import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from .ledger import JsonlLedger
from .assessment import assess_market
from .schemas import (
    AssetSnapshot,
    ContinuousJudgment,
    MarketReport,
    MarketSnapshot,
    MarketStateFrame,
    OutcomeReview,
    OutcomeCalibration,
    ResearchEvent,
)


HORIZONS = {"6h": timedelta(hours=6), "24h": timedelta(hours=24), "7d": timedelta(days=7)}
MAX_REVIEW_SAMPLE_DELAY = timedelta(minutes=15)


class OutcomeReviewer:
    """Append-only deterministic event and outcome review store."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def open_event(
        self,
        snapshot: MarketSnapshot,
        asset: AssetSnapshot,
        frame: MarketStateFrame,
        judgment: ContinuousJudgment,
        report: Optional[MarketReport],
    ) -> ResearchEvent:
        opened = _parse_time(snapshot.as_of)
        event = ResearchEvent(
            event_id="{}:{}".format(judgment.asset, judgment.frame_id),
            asset=judgment.asset,
            opened_at=snapshot.as_of,
            original_snapshot=asset,
            original_frame=frame,
            original_judgment=judgment,
            report=report,
            review_due_at={name: _format_time(opened + delta) for name, delta in HORIZONS.items()},
        )
        if event.event_id not in {item.event_id for item in self.events()}:
            self._append(self.root / "events.jsonl", event.model_dump_json())
        return event

    def events(self) -> List[ResearchEvent]:
        path = self.root / "events.jsonl"
        if not path.exists():
            return []
        return [ResearchEvent.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def reviews(self) -> List[OutcomeReview]:
        directory = self.root / "outcomes"
        if not directory.exists():
            return []
        reviews = []
        for path in sorted(directory.glob("*.jsonl")):
            reviews.extend(
                OutcomeReview.model_validate_json(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        return reviews

    def review_due(self, snapshot: MarketSnapshot, ledger: JsonlLedger) -> List[OutcomeReview]:
        now = _parse_time(snapshot.as_of)
        existing = {(item.event_id, item.horizon) for item in self.reviews()}
        completed = []
        for event in self.events():
            frames = ledger.frames(event.asset)
            for horizon, due_at in event.review_due_at.items():
                due = _parse_time(due_at)
                if (event.event_id, horizon) in existing or now < due:
                    continue
                sample = _nearest_horizon_frame(frames, event.opened_at, due, now)
                if sample is None:
                    review = _insufficient_review(event, horizon, snapshot.as_of)
                else:
                    sample_time = _parse_time(sample.frame.as_of)
                    review = _build_review(
                        event,
                        horizon,
                        snapshot.as_of,
                        sample.frame.as_of,
                        int((sample_time - due).total_seconds()),
                        sample.asset_snapshot,
                        frames,
                    )
                path = self.root / "outcomes" / "{}.jsonl".format(snapshot.as_of[:10])
                self._append(path, review.model_dump_json())
                existing.add((event.event_id, horizon))
                completed.append(review)
        if completed:
            self.write_calibration_report()
        return completed

    def calibration_summary(self) -> List[OutcomeCalibration]:
        groups = {}
        for review in self.reviews():
            if review.status != "complete":
                continue
            groups.setdefault((review.original_state, review.horizon), []).append(review)
        summaries = []
        for (state, horizon), reviews in sorted(groups.items()):
            summaries.append(OutcomeCalibration(
                state=state,
                horizon=horizon,
                sample_count=len(reviews),
                average_return=_average(item.realized_return for item in reviews),
                average_max_favorable_excursion=_average(
                    item.max_favorable_excursion for item in reviews
                ),
                average_max_adverse_excursion=_average(
                    item.max_adverse_excursion for item in reviews
                ),
                invalidation_rate=sum(bool(item.invalidation_triggered) for item in reviews) / len(reviews),
            ))
        return summaries

    def write_calibration_report(self) -> Path:
        path = self.root / "calibration_report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [item.model_dump() for item in self.calibration_summary()]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def _append(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")


def _build_review(
    event: ResearchEvent,
    horizon: str,
    reviewed_at: str,
    sample_time: str,
    sample_delay_seconds: int,
    current: AssetSnapshot,
    frames,
) -> OutcomeReview:
    original = event.original_snapshot
    returns = []
    if original.spot_price:
        for record in frames:
            frame_time = _parse_time(record.frame.as_of)
            if frame_time < _parse_time(event.opened_at) or frame_time > _parse_time(sample_time):
                continue
            price = record.asset_snapshot.spot_price
            if price is not None:
                returns.append((price - original.spot_price) / original.spot_price)
    realized_return = None
    if original.spot_price and current.spot_price is not None:
        realized_return = (current.spot_price - original.spot_price) / original.spot_price
        returns.append(realized_return)
    funding_change = _difference(current.funding_rate, original.funding_rate)
    oi_change = _relative_change(current.open_interest, original.open_interest)
    invalidated = _invalidation_triggered(event.original_judgment.selected_value, current)
    return OutcomeReview(
        review_id="{}:{}".format(event.event_id, horizon),
        event_id=event.event_id,
        asset=event.asset,
        horizon=horizon,
        reviewed_at=reviewed_at,
        sample_time=sample_time,
        sample_delay_seconds=sample_delay_seconds,
        original_state=event.original_judgment.selected_value,
        realized_return=realized_return,
        max_favorable_excursion=max(returns) if returns else None,
        max_adverse_excursion=min(returns) if returns else None,
        funding_change=funding_change,
        open_interest_change=oi_change,
        spot_confirmation=current.spot_volume_change_1h is not None and current.spot_volume_change_1h > 0.05,
        invalidation_triggered=invalidated,
    )


def _nearest_horizon_frame(frames, opened_at: str, due: datetime, now: datetime):
    opened = _parse_time(opened_at)
    eligible = [
        record for record in frames
        if opened <= _parse_time(record.frame.as_of) <= now
    ]
    if not eligible:
        return None
    closest = min(eligible, key=lambda record: abs(_parse_time(record.frame.as_of) - due))
    if abs(_parse_time(closest.frame.as_of) - due) > MAX_REVIEW_SAMPLE_DELAY:
        return None
    return closest


def _insufficient_review(
    event: ResearchEvent,
    horizon: str,
    reviewed_at: str,
) -> OutcomeReview:
    return OutcomeReview(
        review_id="{}:{}".format(event.event_id, horizon),
        event_id=event.event_id,
        asset=event.asset,
        horizon=horizon,
        reviewed_at=reviewed_at,
        status="insufficient_data",
        original_state=event.original_judgment.selected_value,
    )


def _invalidation_triggered(state: str, current: AssetSnapshot) -> bool:
    state = {
        "leverage_led": "leverage_expansion_up",
        "spot_confirmed": "spot_confirmed_up",
        "deleveraging": "position_unwind_down",
    }.get(state, state)
    assessment = assess_market(current)
    if state.startswith("leverage_expansion"):
        return assessment.leverage_change != "expanding" or assessment.spot_confirmation == "strong"
    if state.startswith("spot_confirmed"):
        return assessment.spot_confirmation != "strong" or assessment.leverage_change != "stable"
    if state.startswith("position_unwind"):
        return assessment.leverage_change != "contracting"
    if state.startswith("broad_participation"):
        return not (
            assessment.spot_confirmation == "strong"
            and assessment.leverage_change == "expanding"
        )
    if state.startswith("unconfirmed_move"):
        return not (
            assessment.leverage_change == "stable"
            and assessment.spot_confirmation != "strong"
        )
    if state == "quiet":
        return assessment.regime != "quiet"
    if state == "conflicting":
        return assessment.alignment != "conflicting"
    if state == "insufficient_data":
        return assessment.data_quality != "insufficient"
    return False


def _difference(current: Optional[float], original: Optional[float]) -> Optional[float]:
    return None if current is None or original is None else current - original


def _relative_change(current: Optional[float], original: Optional[float]) -> Optional[float]:
    if current is None or original in {None, 0}:
        return None
    return (current - original) / original


def _average(values) -> Optional[float]:
    available = [value for value in values if value is not None]
    return None if not available else sum(available) / len(available)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
