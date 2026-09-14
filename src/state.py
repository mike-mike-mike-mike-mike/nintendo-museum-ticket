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


def target_range(document: dict) -> dict:
    range_value = document.get("config", {}).get("target_range")
    if not range_value or not isinstance(range_value, dict):
        raise MalformedStateError("config.target_range must be an object")
    return range_value


def available(document: dict) -> set[str]:
    return set(document.get("state", {}).get("available", []))


def save_available(document: dict, new_available: set[str], path: Path = DEFAULT_PATH) -> None:
    """Replace only state.available, leaving config untouched."""
    document.setdefault("state", {})["available"] = sorted(new_available)
    Path(path).write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
