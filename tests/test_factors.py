from tellagent.factors import JsonlFactorStore, build_factor_hypotheses
from tellagent.observer import RuleBasedJevObserver, build_state_frame
from tellagent.schemas import FactorResult
from tellagent.strategy import build_research_guidance
from helpers import market_snapshot


def test_factor_hypotheses_are_structured_and_deduplicated(tmp_path):
    snapshot = market_snapshot()
    judgment = RuleBasedJevObserver().judge(build_state_frame(snapshot, snapshot.assets[1]))
    guidance = build_research_guidance(judgment)
    hypotheses = build_factor_hypotheses(judgment, guidance, None)
    assert {item.name for item in hypotheses} == {
        "leverage_dominance", "spot_derivatives_divergence"
    }
    assert all(item.inputs and item.formula_draft and item.test_plan for item in hypotheses)

    store = JsonlFactorStore(tmp_path)
    store.append_hypothesis(hypotheses[0])
    store.append_hypothesis(hypotheses[0])
    assert len(store.hypotheses()) == 1
    draft = (tmp_path / "worldquant_drafts.md").read_text()
    assert "not directly submittable alphas" in draft
    assert "<BRAIN_FIELD>" in draft
    assert hypotheses[0].formula_draft in draft


def test_factor_result_contract_can_be_persisted(tmp_path):
    store = JsonlFactorStore(tmp_path)
    result = FactorResult(
        result_id="result-1", hypothesis_id="hypothesis-1",
        tested_at="2026-10-13T00:00:00Z", sample="out_of_sample", rank_ic=0.03,
    )
    store.append_result(result)
    assert "hypothesis-1" in (tmp_path / "factor_results.jsonl").read_text()
