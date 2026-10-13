from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .schemas import (
    AssetSnapshot,
    ContinuousJudgment,
    FrameLedgerRecord,
    MarketSnapshot,
    MarketStateFrame,
)


class JsonlLedger:
    """Append-only point-in-time frame and judgment ledger."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def append_frame(
        self,
        snapshot: MarketSnapshot,
        asset: AssetSnapshot,
        frame: MarketStateFrame,
    ) -> FrameLedgerRecord:
        recorded_at = _now()
        record = FrameLedgerRecord(
            record_id=frame.frame_id,
            recorded_at=recorded_at,
            available_time=snapshot.available_time or snapshot.as_of,
            received_time=snapshot.received_time or snapshot.as_of,
            sources=snapshot.sources,
            source_times=_asset_metadata(snapshot.source_times, asset.symbol),
            payload_hashes=_asset_metadata(snapshot.payload_hashes, asset.symbol),
            asset_snapshot=asset,
            frame=frame,
        )
        self._append("frames", frame.as_of, record.model_dump_json())
        return record

    def append_judgment(self, judgment: ContinuousJudgment) -> None:
        self._append("judgments", judgment.as_of, judgment.model_dump_json())

    def judgments(self, asset: Optional[str] = None) -> List[ContinuousJudgment]:
        records: List[ContinuousJudgment] = []
        directory = self.root / "judgments"
        if not directory.exists():
            return records
        for path in sorted(directory.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                judgment = ContinuousJudgment.model_validate_json(line)
                if asset is None or judgment.asset.upper() == asset.upper():
                    records.append(judgment)
        return records

    def frames(self, asset: Optional[str] = None) -> List[FrameLedgerRecord]:
        records: List[FrameLedgerRecord] = []
        directory = self.root / "frames"
        if not directory.exists():
            return records
        for path in sorted(directory.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = FrameLedgerRecord.model_validate_json(line)
                if asset is None or record.frame.asset.upper() == asset.upper():
                    records.append(record)
        return records

    def latest_judgment(self, asset: str) -> Optional[ContinuousJudgment]:
        matches = self.judgments(asset)
        return matches[-1] if matches else None

    def _append(self, category: str, as_of: str, payload: str) -> None:
        directory = self.root / category
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "{}.jsonl".format(as_of[:10])
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")


def _asset_metadata(values: dict[str, str], symbol: str) -> dict[str, str]:
    suffix = ":{}".format(symbol.upper())
    return {key: value for key, value in values.items() if key.upper().endswith(suffix)}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
