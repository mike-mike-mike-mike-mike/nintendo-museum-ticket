import calendar
import re
from datetime import date

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_month(value: str) -> tuple[int, int]:
    """Parse a 'YYYY-MM' config string into (year, month)."""
    match = _MONTH_RE.match(value or "")
    if not match:
        raise ValueError(f"target month must look like 'YYYY-MM', got {value!r}")
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"month out of range in {value!r}")
    return year, month


def is_fully_elapsed(value: str, today: date) -> bool:
    """True when every day of the given month is strictly in the past."""
    year, month = parse_month(value)
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day) < today
