#!/usr/bin/env python3
import sys
from datetime import date as date_type
from datetime import datetime

from dotenv import load_dotenv

from src import state as state_module
from src.monitor import (
    FatalFetchError,
    NintendoMuseumMonitor,
    TransientFetchError,
    available_dates,
)
from src.date_range import months_spanned, parse_range
from src.notifier import send_availability_email
from src.state import MalformedStateError
from src.retry import with_retry
from utils.logging_setter import setup_logger

load_dotenv()

logger = setup_logger("nintendo_main", "nintendo_main.log")

EXIT_OK = 0
EXIT_FAILURE = 1


def run(path=None, today: date_type | None = None, monitor=None, sender=None) -> int:
    """Perform one availability check. Returns the process exit code."""
    path = path or state_module.DEFAULT_PATH
    today = today or datetime.now().date()
    monitor = monitor or NintendoMuseumMonitor()
    sender = sender or send_availability_email

    try:
        document = state_module.load(path)
        target_range = state_module.target_range(document)
        start, end = parse_range(target_range)
    except MalformedStateError as exc:
        logger.error("Cannot read %s: %s", path, exc)
        return EXIT_FAILURE
    except (ValueError, TypeError) as exc:
        logger.error("Invalid config.target_range (%s): %s", path, exc)
        return EXIT_FAILURE

    if end < today:
        logger.warning(
            "Configured target range (%s to %s) has fully elapsed. Nothing to check — "
            "update config.target_range in %s.", start, end, path,
        )
        return EXIT_OK

    current: set[str] = set()
    for year, month_number in months_spanned(max(start, today), end):
        try:
            payload = with_retry(lambda: monitor.fetch_calendar(year, month_number))
        except TransientFetchError as exc:
            logger.warning("Transient fetch failure, leaving state untouched: %s", exc)
            return EXIT_OK
        except FatalFetchError as exc:
            logger.error("Fatal fetch failure: %s", exc)
            return EXIT_FAILURE
        current |= available_dates(payload, today, start=start, end=end)

    previous = state_module.available(document)
    newly_available = current - previous
    logger.info(
        "Checked %s to %s: %d available, %d newly available",
        start, end, len(current), len(newly_available),
    )

    if newly_available:
        try:
            with_retry(lambda: sender(newly_available), retryable_errors=(Exception,))
        except Exception as exc:
            logger.error("Failed to send notification, leaving state untouched: %s", exc)
            return EXIT_FAILURE

    state_module.save_available(document, current, path)
    logger.info("State written with %d available date(s)", len(current))
    return EXIT_OK


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
