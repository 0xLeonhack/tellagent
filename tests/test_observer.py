from tellagent.data import load_fixture
from tellagent.observer import RuleBasedJevObserver, build_state_frame


def test_observer_emits_structured_leverage_judgment():
    snapshot = load_fixture()
    frame = build_state_frame(snapshot, snapshot.assets[1])
    judgment = RuleBasedJevObserver().judge(frame)
    assert judgment.provider == "rule-based-jev"
    assert judgment.selected_value == "leverage_led"
    assert sum(judgment.probabilities.values()) == 1.0
    assert judgment.research_priority in {"watch", "significant", "urgent"}


def test_observer_marks_missing_oi_as_watch():
    snapshot = load_fixture()
    asset = snapshot.assets[0].model_copy(update={"open_interest_change_1h": None})
    frame = build_state_frame(snapshot, asset)
    judgment = RuleBasedJevObserver().judge(frame)
    assert judgment.selected_value == "uncertain"
    assert judgment.research_priority == "watch"
    assert judgment.missing_roles
