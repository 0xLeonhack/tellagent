from .metrics import analysis_fields, analyze_asset
from .schemas import AssetSnapshot, MarketReport, MarketSnapshot


def generate_demo_report(snapshot: MarketSnapshot, asset: AssetSnapshot) -> MarketReport:
    analysis = analyze_asset(asset)
    headline, invalidation, confidence = analysis_fields(analysis)
    return MarketReport(
        asset=asset.symbol,
        headline=headline,
        state=analysis.suggested_state,
        confidence=confidence,
        supporting_evidence=analysis.evidence.supporting,
        contradicting_evidence=analysis.evidence.contradicting,
        missing_evidence=analysis.evidence.missing,
        invalidation_condition=invalidation,
        data_time=snapshot.as_of,
        sources=snapshot.sources,
    )
