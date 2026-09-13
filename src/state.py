import json
from pathlib import Path

DEFAULT_PATH = Path("state.json")


class MalformedStateError(Exception):
    """state.json is missing, unreadable, or missing required configuration."""


def load(path: Path = DEFAULT_PATH) -> dict:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MalformedStateError(f"{path} not found") from exc
    except json.JSONDecodeError as exc:
        raise MalformedStateError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise MalformedStateError(f"{path} must contain a JSON object")
    return document


def target_months(document: dict) -> list[str]:
    months = document.get("config", {}).get("target_months")
    if not months or not isinstance(months, list):
        raise MalformedStateError("config.target_months must be a non-empty list")
    return months


def available(document: dict) -> set[str]:
    return set(document.get("state", {}).get("available", []))


def save_available(document: dict, new_available: set[str], path: Path = DEFAULT_PATH) -> None:
    """Replace only state.available, leaving config untouched."""
    document.setdefault("state", {})["available"] = sorted(new_available)
    Path(path).write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
