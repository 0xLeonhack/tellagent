import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from .schemas import ContinuousJudgment, MarketReport, MemoryRecord


DEFAULT_MEMORY_PATH = Path(".tellagent") / "memory.jsonl"


class JsonlMemory:
    """Small append-only memory store; no database or service required."""

    def __init__(self, path: Path = DEFAULT_MEMORY_PATH):
        self.path = Path(path)

    def append(
        self,
        judgment: ContinuousJudgment,
        summary: str,
        tags: Iterable[str] = (),
        report: Optional[MarketReport] = None,
    ) -> MemoryRecord:
        record = MemoryRecord(
            memory_id="{}:{}:{}".format(judgment.asset, judgment.as_of, judgment.frame_id),
            asset=judgment.asset,
            as_of=judgment.as_of,
            state=judgment.selected_value,
            priority=judgment.research_priority,
            summary=summary,
            tags=list(dict.fromkeys(tags)),
            judgment=judgment,
            report=report,
            created_at=_now(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")
        return record

    def records(self) -> List[MemoryRecord]:
        if not self.path.exists():
            return []
        records: List[MemoryRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(MemoryRecord.model_validate_json(line))
        return records

    def related(
        self,
        asset: str,
        state: Optional[str] = None,
        tags: Iterable[str] = (),
        limit: int = 5,
    ) -> List[MemoryRecord]:
        """Return recent records ranked by simple context overlap."""
        query_tags = {tag.lower() for tag in tags}
        scored = []
        for record in self.records():
            score = 0
            if record.asset.upper() == asset.upper():
                score += 5
            if state and record.state == state:
                score += 4
            score += len(query_tags.intersection({tag.lower() for tag in record.tags})) * 2
            score += len(query_tags.intersection(_tokens(record.summary)))
            if score:
                scored.append((score, record.created_at, record))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [record for _, _, record in scored[:limit]]


def memory_summary(records: Iterable[MemoryRecord], limit: int = 3) -> str:
    selected = list(records)[:limit]
    if not selected:
        return "没有找到相近的历史上下文。"
    return "\n".join(
        "- {} {}: {}".format(record.as_of, record.state, record.summary)
        for record in selected
    )


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[一-鿿]")


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in _TOKEN_PATTERN.findall(value)}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
