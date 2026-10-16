from pathlib import Path

import pytest

from tellagent.agent_policy import RuleBasedAgentProvider
from tellagent.agent_research import AgentRequest, AgentResearchRunner
from tellagent.agent_tools import build_research_tool_registry
from tellagent.factors import JsonlFactorStore
from tellagent.ledger import JsonlLedger
from tellagent.memory import JsonlMemory
from tellagent.metrics import build_deterministic_report
from tellagent.observer import RuleBasedObserver, build_state_frame
from tellagent.research import process_snapshot, replay_recorded_frames
from tellagent.review import OutcomeReviewer
from tellagent.schemas import AssetSnapshot, MarketSnapshot
from tellagent.strategy import build_research_guidance
from tellagent.tools import ToolCall
from tellagent.trends import compute_judgment_trend
from helpers import market_snapshot


def _runner(root: Path, max_steps: int = 3) -> AgentResearchRunner:
    provider = RuleBasedAgentProvider(max_steps=max_steps)
    return AgentResearchRunner(
        root=root,
        decide=provider.decide,
        provider_name=provider.provider,
        model_version=provider.model_version,
        max_steps=max_steps,
        report_builder=lambda request: build_deterministic_report(request.snapshot, request.asset),
        counts_model_calls=False,
        store=JsonlFactorStore(root),
    )


def _request(snapshot: MarketSnapshot, asset: AssetSnapshot) -> AgentRequest:
    frame = build_state_frame(snapshot, asset)
    judgment = RuleBasedObserver().judge(frame)
    return AgentRequest(
        snapshot=snapshot,
        asset=asset,
        frame=frame,
        judgment=judgment,
        trend=compute_judgment_trend(judgment, []),
        guidance=build_research_guidance(judgment),
    )


def test_agent_mode_runs_full_loop_and_writes_every_ledger(tmp_path: Path):
    snapshot = market_snapshot()
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    ledger = JsonlLedger(tmp_path)
    reviewer = OutcomeReviewer(tmp_path)
    factor_store = JsonlFactorStore(tmp_path)

    outcomes = process_snapshot(
        snapshot,
        memory,
        asset="ETH",
        observer=RuleBasedObserver(),
        ledger=ledger,
        reviewer=reviewer,
        factor_store=factor_store,
        agent_runner=_runner(tmp_path),
    )

    outcome = outcomes[0]
    assert outcome.agent_run is not None
    assert outcome.agent_run.actions == ["investigate", "generate_factor", "finish"]
    assert outcome.agent_run.terminal_action == "finish"
    assert outcome.agent_run.terminal_within_budget is True
    assert outcome.agent_run.model_calls == 0
    assert outcome.investigated is True
    assert outcome.report is not None
    assert outcome.report.asset == "ETH"

    hypotheses = factor_store.hypotheses()
    assert len(hypotheses) == 1
    assert hypotheses[0].name == "leverage_dominance"
    assert hypotheses[0].regime == "leverage_expansion_up"
    assert hypotheses[0].source_frame_id == outcome.agent_run.frame_id
    assert outcome.agent_run.factor_hypothesis_ids == [hypotheses[0].hypothesis_id]

    assert len(memory.records()) == 1
    assert len(reviewer.events()) == 1
    assert (tmp_path / "agent_traces" / "2026-10-08.jsonl").exists()
    assert (tmp_path / "memory.jsonl").exists()


def test_agent_mode_monitor_skips_report_and_memory(tmp_path: Path):
    quiet = AssetSnapshot(
        symbol="BTC",
        spot_price=60000.0,
        price_change_1h=0.001,
        price_change_6h=0.002,
        spot_volume_change_1h=0.01,
        funding_rate=0.0001,
        open_interest=1000.0,
        open_interest_change_1h=0.005,
    )
    snapshot = MarketSnapshot(as_of="2026-10-08T00:00:00Z", sources=["Coinbase"], assets=[quiet])
    runner = _runner(tmp_path)
    outcome = runner(_request(snapshot, quiet))

    assert outcome.escalated is False
    assert outcome.report is None
    assert outcome.summary.terminal_action == "monitor"
    assert outcome.summary.steps == 1
    assert outcome.factor_hypotheses == []
    assert len(runner.trace_store.summaries()) == 1


def test_always_investigate_hands_quiet_frames_to_the_agent(tmp_path: Path):
    quiet = AssetSnapshot(
        symbol="BTC",
        spot_price=60000.0,
        price_change_1h=0.001,
        price_change_6h=0.002,
        spot_volume_change_1h=0.01,
        funding_rate=0.0001,
        open_interest=1000.0,
        open_interest_change_1h=0.005,
    )
    snapshot = MarketSnapshot(as_of="2026-10-08T00:00:00Z", sources=["Coinbase"], assets=[quiet])
    memory = JsonlMemory(tmp_path / "memory.jsonl")

    outcomes = process_snapshot(
        snapshot,
        memory,
        asset="BTC",
        observer=RuleBasedObserver(),
        ledger=JsonlLedger(tmp_path),
        factor_store=JsonlFactorStore(tmp_path),
        agent_runner=_runner(tmp_path),
        always_investigate=True,
    )

    outcome = outcomes[0]
    assert outcome.agent_run is not None
    assert outcome.agent_run.terminal_action == "monitor"
    assert outcome.investigated is False
    assert outcome.report is None
    assert memory.records() == []


def test_agent_tools_reject_unknown_factor_names(tmp_path: Path):
    snapshot = market_snapshot()
    asset = snapshot.assets[1]
    frame = build_state_frame(snapshot, asset)
    judgment = RuleBasedObserver().judge(frame)
    registry = build_research_tool_registry(
        tmp_path, frame, judgment, store=JsonlFactorStore(tmp_path)
    )
    rejected = registry.execute(ToolCall(
        call_id="1", tool_name="create_factor_hypothesis", arguments={"name": "free_style_alpha"}
    ))
    assert rejected.ok is False
    assert "unknown factor name" in rejected.error
    assert JsonlFactorStore(tmp_path).hypotheses() == []


def test_agent_mode_records_trace_even_when_the_report_fails(tmp_path: Path):
    snapshot = market_snapshot()
    provider = RuleBasedAgentProvider(max_steps=3)
    runner = AgentResearchRunner(
        root=tmp_path,
        decide=provider.decide,
        provider_name=provider.provider,
        model_version=provider.model_version,
        max_steps=3,
        report_builder=lambda request: None,
        counts_model_calls=False,
    )
    outcome = runner(_request(snapshot, snapshot.assets[1]))
    assert outcome.report is None
    assert outcome.summary.terminal_action == "finish"
    assert len(runner.trace_store.summaries()) == 1


def test_rejected_decision_is_recorded_without_a_report(tmp_path: Path):
    def decide(context, tool_result, step):
        raise ValueError("Remote Agent failed: unknown tool")

    runner = AgentResearchRunner(
        root=tmp_path,
        decide=decide,
        provider_name="remote-agent",
        model_version="deepseek-test",
        max_steps=3,
        report_builder=lambda request: build_deterministic_report(request.snapshot, request.asset),
    )
    snapshot = market_snapshot()
    outcome = runner(_request(snapshot, snapshot.assets[1]))

    assert outcome.escalated is False
    assert outcome.report is None
    assert outcome.summary.terminal_action == "rejected"
    assert outcome.summary.steps == 0
    assert outcome.summary.model_calls == 1
    assert "unknown tool" in outcome.summary.error
    assert outcome.summary.trace.decisions == []
    assert len(runner.trace_store.summaries()) == 1


def test_failed_analyst_keeps_the_error_instead_of_a_report(tmp_path: Path):
    def report_builder(request):
        raise ValueError("Remote analyst failed: timeout")

    provider = RuleBasedAgentProvider(max_steps=3)
    runner = AgentResearchRunner(
        root=tmp_path,
        decide=provider.decide,
        provider_name=provider.provider,
        model_version=provider.model_version,
        max_steps=3,
        report_builder=report_builder,
        counts_model_calls=False,
    )
    snapshot = market_snapshot()
    outcome = runner(_request(snapshot, snapshot.assets[1]))

    assert outcome.escalated is False
    assert outcome.report is None
    assert outcome.summary.terminal_action == "finish"
    assert "timeout" in outcome.summary.error
    assert outcome.summary.report_headline is None


def test_replay_rebuilds_recorded_frames_without_rewriting_the_ledger(tmp_path: Path):
    ledger = JsonlLedger(tmp_path)
    memory = JsonlMemory(tmp_path / "memory.jsonl")
    runner = _runner(tmp_path)

    process_snapshot(
        market_snapshot(),
        memory,
        asset="ETH",
        observer=RuleBasedObserver(),
        ledger=ledger,
        factor_store=JsonlFactorStore(tmp_path),
        agent_runner=runner,
    )
    frames_before = len(ledger.frames())
    judgments_before = len(ledger.judgments())

    outcomes = replay_recorded_frames(ledger, memory, runner, asset="ETH", limit=1)

    outcome = outcomes[0]
    assert outcome.agent_run is not None
    assert outcome.agent_run.frame_id == ledger.frames()[0].record_id
    assert outcome.agent_run.actions == ["investigate", "generate_factor", "finish"]
    assert outcome.report is not None
    # The replay only adds a trace: facts and judgments are left untouched.
    assert len(ledger.frames()) == frames_before
    assert len(ledger.judgments()) == judgments_before
    assert len(memory.records()) == 1
    assert len(runner.trace_store.summaries()) == 2


def test_replay_hides_records_newer_than_the_frame_under_study(tmp_path: Path):
    ledger = JsonlLedger(tmp_path)
    snapshot = market_snapshot()
    asset = snapshot.assets[1]
    frame = build_state_frame(snapshot, asset)
    ledger.append_judgment(RuleBasedObserver().judge(frame))
    later = RuleBasedObserver().judge(frame.model_copy(update={
        "as_of": "2026-10-09T00:00:00Z", "frame_id": "frame-later",
    }))
    ledger.append_judgment(later)

    registry = build_research_tool_registry(
        tmp_path, frame, RuleBasedObserver().judge(frame),
        store=JsonlFactorStore(tmp_path), as_of_cutoff=frame.as_of,
    )
    result = registry.execute(ToolCall(
        call_id="1", tool_name="read_recent_judgments", arguments={"limit": 10}
    ))

    assert result.ok is True
    assert result.data["count"] == 1
    assert [item["as_of"] for item in result.data["judgments"]] == [frame.as_of]


def test_model_driven_agent_respects_the_model_call_budget(tmp_path: Path):
    provider = RuleBasedAgentProvider(max_steps=5)
    with pytest.raises(ValueError, match="limited to 3 calls"):
        AgentResearchRunner(
            root=tmp_path,
            decide=provider.decide,
            provider_name="remote-agent",
            model_version="deepseek-test",
            max_steps=5,
            counts_model_calls=True,
        )
