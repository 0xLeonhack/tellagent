import json
from pathlib import Path
from typing import Union

from .schemas import MarketSnapshot


DEFAULT_FIXTURE = Path(__file__).parent / "fixtures" / "demo_snapshot.json"


def load_fixture(path: Union[str, Path] = DEFAULT_FIXTURE) -> MarketSnapshot:
    fixture_path = Path(path)
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("Fixture file not found: %s" % fixture_path) from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Fixture is not valid JSON: %s" % fixture_path) from exc
    return MarketSnapshot.model_validate(payload)
