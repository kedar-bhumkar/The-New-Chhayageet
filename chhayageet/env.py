from __future__ import annotations

from os import environ
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_environment() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def env_path(name: str, default: str | None = None) -> Path | None:
    value = environ.get(name, default)
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path
