import json
import time
from pathlib import Path
from typing import Callable, Iterable, Optional, TextIO

from .data import DEFAULT_FIXTURE, SCENARIO_FIXTURES, load_fixture, load_live_snapshot
from .observer import RuleBasedJevObserver, build_state_frame
from .schemas import ContinuousJudgment, MarketSnapshot


def observe_snapshot(snapshot: MarketSnapshot, asset: Optional[str] = None) -> list[ContinuousJudgment]:
    observer = RuleBasedJevObserver()
    selected = [item for item in snapshot.assets if not asset or item.symbol.upper() == asset.upper()]
    if not selected:
        raise ValueError("Asset not found in snapshot: {}".format(asset))
    return [observer.judge(build_state_frame(snapshot, item)) for item in selected]


def load_observation_snapshot(
    fixture: bool = True,
    scenario: str = "default",
    path: Optional[Path] = None,
    timeout: float = 8.0,
) -> MarketSnapshot:
    if fixture:
        if path and scenario != "default":
            raise ValueError("--path and a non-default --scenario cannot be used together.")
        if scenario not in SCENARIO_FIXTURES:
            raise ValueError("--scenario must be default, leverage, or spot.")
        return load_fixture(path or SCENARIO_FIXTURES[scenario])
    if path or scenario != "default":
        raise ValueError("--path and --scenario only apply to --fixture mode.")
    return load_live_snapshot(timeout=timeout)


def write_judgments(judgments: Iterable[ContinuousJudgment], output: TextIO) -> None:
    for judgment in judgments:
        output.write(json.dumps(judgment.model_dump(), ensure_ascii=False) + "\n")
    output.flush()


def run_observer(
    snapshot_loader: Callable[[], MarketSnapshot],
    asset: Optional[str] = None,
    cycles: int = 1,
    interval: float = 300.0,
    output: Optional[TextIO] = None,
) -> int:
    """Run finite or continuous observation; cycles=0 means run until interrupted."""
    if cycles < 0:
        raise ValueError("cycles must be zero or greater")
    if interval < 0:
        raise ValueError("interval must be zero or greater")
    import sys

    destination = output or sys.stdout
    completed = 0
    while cycles == 0 or completed < cycles:
        snapshot = snapshot_loader()
        write_judgments(observe_snapshot(snapshot, asset), destination)
        completed += 1
        if cycles == 0 or completed < cycles:
            time.sleep(interval)
    return completed
