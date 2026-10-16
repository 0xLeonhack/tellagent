from pathlib import Path

from dotenv import load_dotenv


def load_project_env() -> None:
    """Load the project .env without overriding explicit shell variables."""
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env", override=False)
