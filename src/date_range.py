from datetime import date


def parse_range(value: dict) -> tuple[date, date]:
    """Parse a {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"} config value."""
    if not isinstance(value, dict):
        raise ValueError(f"target range must be an object, got {value!r}")
    start_str, end_str = value.get("start_date"), value.get("end_date")
    if not start_str or not end_str:
        raise ValueError(f"target range must have start_date and end_date, got {value!r}")
    start = date.fromisoformat(start_str)
    end = date.fromisoformat(end_str)
    if start > end:
        raise ValueError(f"start_date must not be after end_date, got {value!r}")
    return start, end


def months_spanned(start: date, end: date) -> list[tuple[int, int]]:
    """The distinct (year, month) pairs from start's month through end's month."""
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months
