from datetime import date, datetime

from curl_cffi import requests

from utils.logging_setter import setup_logger

logger = setup_logger("nintendo_monitor", "nintendo_monitor.log")

TRANSIENT_STATUSES = {429, 500, 502, 503, 504}
BLOCKED_STATUSES = {401, 403}


class TransientFetchError(Exception):
    """A retryable upstream problem. The caller should warn and exit 0."""


class FatalFetchError(Exception):
    """A problem that will not fix itself. The caller should exit non-zero."""


def available_dates(calendar_data: dict | None, today: date) -> set[str]:
    """Dates that are on sale, open, and strictly in the future."""
    if not calendar_data:
        return set()
    calendar = calendar_data.get("data", {}).get("calendar", {})
    found = set()
    for date_str, info in calendar.items():
        if info.get("sale_status") != 1 or info.get("open_status") != 1:
            continue
        if datetime.strptime(date_str, "%Y-%m-%d").date() <= today:
            continue
        found.add(date_str)
    return found


class NintendoMuseumMonitor:
    """Fetches the Nintendo Museum ticket calendar."""

    BASE_URL = "https://museum-tickets.nintendo.com"

    def __init__(self):
        self.api_url = f"{self.BASE_URL}/en/api/calendar"

    def _headers(self) -> dict:
        return {
            "Connection": "keep-alive",
            "sec-ch-ua-platform": '"macOS"',
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
            "sec-ch-ua-mobile": "?0",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": f"{self.BASE_URL}/en/calendar",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def fetch_calendar(self, year: int, month: int) -> dict:
        """Fetch one month. Raises TransientFetchError or FatalFetchError."""
        try:
            response = requests.get(
                self.api_url,
                params={"target_year": year, "target_month": month},
                headers=self._headers(),
                impersonate="chrome110",
                timeout=30,
            )
        except Exception as exc:
            raise TransientFetchError(f"network error fetching {year}-{month:02d}: {exc}") from exc

        status = response.status_code
        if status in BLOCKED_STATUSES:
            raise FatalFetchError(
                f"HTTP {status} fetching {year}-{month:02d}. This most likely means the "
                f"request was blocked (datacenter IP). Body head: {response.text[:200]!r}"
            )
        if status in TRANSIENT_STATUSES:
            raise TransientFetchError(f"HTTP {status} fetching {year}-{month:02d}")
        if status != 200:
            raise FatalFetchError(f"unexpected HTTP {status} fetching {year}-{month:02d}")

        try:
            payload = response.json()
        except Exception as exc:
            raise FatalFetchError(
                f"response for {year}-{month:02d} was not JSON: {response.text[:200]!r}"
            ) from exc

        if "calendar" not in payload.get("data", {}):
            raise FatalFetchError(
                f"response for {year}-{month:02d} has no data.calendar key: {payload!r}"
            )

        logger.info("Fetched calendar for %d-%02d", year, month)
        return payload
