import pytest
from pydantic import ValidationError

from tellagent.schemas import AssetSnapshot, MarketReport


def test_report_rejects_confidence_outside_range():
    with pytest.raises(ValidationError):
        MarketReport(
            asset="BTC",
            metrics=AssetSnapshot(symbol="BTC"),
            headline="test",
            state="uncertain",
            confidence=1.1,
            supporting_evidence=["x"],
            contradicting_evidence=["y"],
            data_time="2026-10-04T08:00:00Z",
            sources=["test"],
            invalidation_condition="test",
        )
