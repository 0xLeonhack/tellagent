import pytest

from tellagent.evidence import build_evidence_catalog, resolve_evidence_ids
from tellagent.schemas import EvidenceBundle


def test_evidence_ids_are_stable_and_role_scoped():
    bundle = EvidenceBundle(
        supporting=["OI 上升"], contradicting=["现货也增长"], missing=["缺少链上数据"]
    )
    first = build_evidence_catalog("ETH", bundle)
    second = build_evidence_catalog("ETH", bundle)
    assert first == second
    supporting_id = next(item.evidence_id for item in first if item.role == "supporting")
    assert resolve_evidence_ids([supporting_id], "supporting", first) == ["OI 上升"]
    with pytest.raises(ValueError, match="unknown contradicting evidence id"):
        resolve_evidence_ids([supporting_id], "contradicting", first)
