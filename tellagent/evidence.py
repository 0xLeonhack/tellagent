from hashlib import sha256
from typing import Iterable, List

from .schemas import EvidenceBundle, EvidenceItem


def build_evidence_catalog(asset: str, bundle: EvidenceBundle) -> List[EvidenceItem]:
    catalog = []
    groups = (
        ("supporting", bundle.supporting),
        ("contradicting", bundle.contradicting),
        ("missing", bundle.missing),
    )
    for role, statements in groups:
        for statement in statements:
            digest = sha256("{}:{}:{}".format(asset, role, statement).encode()).hexdigest()[:12]
            catalog.append(EvidenceItem(
                evidence_id="{}:{}:{}".format(asset, role, digest),
                role=role,
                statement=statement,
            ))
    return catalog


def resolve_evidence_ids(
    ids: Iterable[str],
    role: str,
    catalog: Iterable[EvidenceItem],
) -> List[str]:
    allowed = {item.evidence_id: item.statement for item in catalog if item.role == role}
    unknown = [evidence_id for evidence_id in ids if evidence_id not in allowed]
    if unknown:
        raise ValueError("Model selected unknown {} evidence id: {}".format(role, unknown[0]))
    return [allowed[evidence_id] for evidence_id in ids]
