# Nintendo Museum Monitor — Scheduled Actions + Email Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the long-running Discord-notifying monitor into a single-shot job that GitHub Actions runs every 5 minutes, persisting config and state in a committed `state.json` and notifying by Gmail SMTP.

**Architecture:** `main.py` becomes a single-shot orchestrator with no loop. It reads `state.json` (human-owned `config` section, job-owned `state` section), fetches the configured months from the Nintendo calendar API, emails the set difference `current - previous` as one email, then writes state back. The workflow commits `state.json` only when it actually changed. Fetch errors are classified: transient ones exit 0, a 401/403 exits non-zero because it most likely means the runner is IP-blocked.

**Tech Stack:** Python 3.13, `uv` + `uv.lock`, `curl_cffi` (TLS impersonation), stdlib `smtplib`/`email.message`, `pytest`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-12-github-actions-email-monitor-design.md`

## Global Constraints

- Python `>=3.13`; dependency management is `pyproject.toml` + `uv.lock`. There is **no** `requirements.txt`. Install with `uv sync --frozen`, run with `uv run`.
- Email uses **stdlib only** (`smtplib`, `email.message`). Do not add an email dependency.
- The job writes **only** the `state` section of `state.json`. The `config` section is human-owned and must survive every write byte-for-identical in content.
- `state.available` is the set of **currently available** dates, never an append-only notified log.
- No `last_run` or any per-run timestamp in `state.json` — it would cause a commit every 5 minutes.
- Notify condition is unchanged from existing code: `sale_status == 1 and open_status == 1` and the date is strictly in the future.
- One email per run listing all new dates. Never one email per date.
- Workflow permissions are exactly `contents: write`. Nothing broader.
- Secrets `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `NOTIFY_EMAIL_TO` reach Python only via environment variables. Never in `state.json`, source, or workflow YAML.
- Gmail SMTP: `smtp.gmail.com` port `587`, STARTTLS.
- State is written **only** on a fully successful fetch of every configured month, and only after a required email has succeeded.

---

## File Structure

| File | Responsibility |
|---|---|
| `.github/workflows/probe.yml` | **Throwaway.** Step-0 datacenter-IP check. Deleted in Task 10. |
| `.github/workflows/monitor.yml` | Schedule, run, commit state |
| `main.py` | Single-shot orchestration, exit codes |
| `src/monitor.py` | Calendar fetch + error classification + pure availability filter |
| `src/months.py` | `YYYY-MM` parsing and elapsed-month check |
| `src/state.py` | `state.json` load/save, config preservation |
| `src/notifier.py` | Gmail SMTP email composition and send |
| `state.json` | Config (`target_months`) + state (`available`) |
| `tests/conftest.py` | Shared calendar fixture |
| `tests/test_*.py` | One test module per source module |
| Deleted | `utils/load_proxies.py`, `utils/discord_utils.py` |

`utils/logging_setter.py` is left exactly as-is per decision — it already calls `os.makedirs(..., exist_ok=True)` and attaches a `StreamHandler`, so it works on a fresh runner and its output lands in the Actions log.

---

### Task 1: Step-0 probe — does the calendar API answer a GitHub runner?

**This task gates every other task.** `src/monitor.py` uses `curl_cffi` with `impersonate="chrome110"` and supported residential proxies, which strongly suggests Nintendo blocks datacenter traffic. GitHub runners are datacenter IPs. Do not start Task 2 until this returns 200.

**Files:**
- Create: `.github/workflows/probe.yml`

- [ ] **Step 1: Create the probe workflow**

```yaml
name: Step 0 Probe
on: workflow_dispatch

jobs:
  probe:
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv sync --frozen
      - name: Fetch calendar and report status
        run: |
          uv run python - <<'PY'
          from curl_cffi import requests
          H = {
              "X-Requested-With": "XMLHttpRequest",
              "Accept": "application/json, text/plain, */*",
              "Referer": "https://museum-tickets.nintendo.com/en/calendar",
              "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
          }
          r = requests.get(
              "https://museum-tickets.nintendo.com/en/api/calendar",
              params={"target_year": 2026, "target_month": 12},
              headers=H, impersonate="chrome110", timeout=30,
          )
          print("HTTP STATUS:", r.status_code)
          print("BODY HEAD:", r.text[:400])
          r.raise_for_status()
          days = r.json()["data"]["calendar"]
          print("DAYS RETURNED:", len(days))
          PY
```

- [ ] **Step 2: Commit and push the probe**

```bash
git add .github/workflows/probe.yml
git commit -m "chore: add step-0 probe to verify calendar API from a runner"
git push
```

- [ ] **Step 3: Run it and read the status code**

Run: `gh workflow run "Step 0 Probe"` then `gh run watch`

Expected: `HTTP STATUS: 200` and `DAYS RETURNED: 31`.

- [ ] **Step 4: Decide**

- **200** → proceed to Task 2.
- **403 or 401** → **STOP.** The runner is IP-blocked and this architecture is void. Report to the user; proxies become mandatory and the spec needs revisiting. Do not attempt workarounds unilaterally.
- **Anything else** → report the status and body to the user before proceeding.

---

### Task 2: Test scaffolding and the shared calendar fixture

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/conftest.py`

**Interfaces:**
- Produces: pytest fixture `calendar_payload` — a dict shaped exactly like the live API response, containing one available day, one closed day, one not-on-sale day, and one past day.

- [ ] **Step 1: Add pytest as a dev dependency**

In `pyproject.toml`, change the `[dependency-groups]` block to:

```toml
[dependency-groups]
dev = ["pyinstaller>=6.12.0,<7", "pytest>=8.0.0"]
```

Also add this block, so `from src.months import ...` resolves from the repo root
deterministically rather than as a side effect of the project being installed:

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
```

- [ ] **Step 2: Sync and confirm pytest is available**

Run: `uv sync && uv run pytest --version`
Expected: prints a pytest 8.x version.

- [ ] **Step 3: Create the fixture**

Create `tests/conftest.py`. Field shapes are copied from a real 2026-12 response.

```python
import pytest


def _day(sale_status, open_status, *, off=False):
    return {
        "apply_type": 2,
        "sale_status": sale_status,
        "open_status": open_status,
        "holiday": None,
        "day_label": {"color_code": 1, "message": "off"} if off else None,
        "is_temporary_closure": False,
        "temporary_closure_time": None,
        "is_holding": False,
    }


@pytest.fixture
def calendar_payload():
    """Mirrors GET /en/api/calendar. Today is assumed to be 2026-12-10 in tests."""
    return {
        "data": {
            "calendar": {
                "2026-12-05": _day(1, 1),   # past, available -> excluded
                "2026-12-15": _day(1, 1),   # future, available -> INCLUDED
                "2026-12-16": _day(1, 1),   # future, available -> INCLUDED
                "2026-12-17": _day(2, 1),   # not on sale -> excluded
                "2026-12-18": _day(1, 2, off=True),  # museum closed -> excluded
            }
        }
    }
```

- [ ] **Step 4: Verify collection works**

Run: `uv run pytest tests/ -v`
Expected: `no tests ran` with no collection errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/conftest.py
git commit -m "test: add pytest and shared calendar fixture"
```

---

### Task 3: `src/months.py` — month parsing and elapsed check

**Files:**
- Create: `src/months.py`
- Test: `tests/test_months.py`

**Interfaces:**
- Produces:
  - `parse_month(value: str) -> tuple[int, int]` — `"2026-12"` → `(2026, 12)`; raises `ValueError` on anything else.
  - `is_fully_elapsed(value: str, today: datetime.date) -> bool` — True when the month's last day is strictly before `today`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_months.py`:

```python
from datetime import date

import pytest

from src.months import is_fully_elapsed, parse_month


def test_parse_month_splits_year_and_month():
    assert parse_month("2026-12") == (2026, 12)


def test_parse_month_rejects_malformed_values():
    for bad in ["2026", "2026-13", "2026-00", "dec-2026", "2026-1", ""]:
        with pytest.raises(ValueError):
            parse_month(bad)


def test_is_fully_elapsed_false_during_the_month():
    assert is_fully_elapsed("2026-12", date(2026, 12, 10)) is False


def test_is_fully_elapsed_false_on_the_last_day():
    assert is_fully_elapsed("2026-12", date(2026, 12, 31)) is False


def test_is_fully_elapsed_true_after_the_month():
    assert is_fully_elapsed("2026-12", date(2027, 1, 1)) is True
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_months.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.months'`

- [ ] **Step 3: Implement**

Create `src/months.py`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_months.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/months.py tests/test_months.py
git commit -m "feat: add month parsing and elapsed-month helpers"
```

---

### Task 4: `src/monitor.py` — pure availability filter

Extract the availability decision out of the class as a pure function so it can be tested without network or state. The class's `check_availability` consulted `self.notified_dates`; that responsibility moves to the set difference in `main.py`.

**Files:**
- Modify: `src/monitor.py`
- Test: `tests/test_availability.py`

**Interfaces:**
- Produces: `available_dates(calendar_data: dict, today: datetime.date) -> set[str]` — returns `YYYY-MM-DD` strings where `sale_status == 1` and `open_status == 1` and the date is strictly after `today`. Returns an empty set for `None` or a payload missing `data`/`calendar`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_availability.py`:

```python
from datetime import date

from src.monitor import available_dates

TODAY = date(2026, 12, 10)


def test_includes_only_future_open_and_on_sale_days(calendar_payload):
    assert available_dates(calendar_payload, TODAY) == {"2026-12-15", "2026-12-16"}


def test_excludes_past_dates_even_when_available(calendar_payload):
    assert "2026-12-05" not in available_dates(calendar_payload, TODAY)


def test_excludes_closed_museum_days(calendar_payload):
    assert "2026-12-18" not in available_dates(calendar_payload, TODAY)


def test_excludes_not_on_sale_days(calendar_payload):
    assert "2026-12-17" not in available_dates(calendar_payload, TODAY)


def test_empty_for_missing_or_malformed_payloads():
    assert available_dates(None, TODAY) == set()
    assert available_dates({}, TODAY) == set()
    assert available_dates({"data": {}}, TODAY) == set()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_availability.py -v`
Expected: FAIL — `ImportError: cannot import name 'available_dates'`

- [ ] **Step 3: Implement**

Add to `src/monitor.py` at module level (above the class):

```python
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
```

Ensure `from datetime import date, datetime` is imported at the top of the file.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_availability.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/monitor.py tests/test_availability.py
git commit -m "feat: extract pure availability filter from monitor class"
```

---

### Task 5: `src/monitor.py` — fetch with transient/fatal error classification

**Files:**
- Modify: `src/monitor.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Produces:
  - `class TransientFetchError(Exception)` — caller should warn and exit 0.
  - `class FatalFetchError(Exception)` — caller should exit non-zero.
  - `NintendoMuseumMonitor()` with no constructor arguments and no proxy or webhook attributes.
  - `NintendoMuseumMonitor.fetch_calendar(year: int, month: int) -> dict` — returns the parsed payload, raises one of the two errors above.

Classification, from the spec: 429 and 5xx and network/timeout errors are transient; 401 and 403 and a 200 whose body is not the expected shape are fatal. A 403 most likely means the runner's IP is blocked and must never be swallowed.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fetch.py`:

```python
import pytest

from src import monitor as monitor_module
from src.monitor import FatalFetchError, NintendoMuseumMonitor, TransientFetchError


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _patch_get(monkeypatch, result):
    def fake_get(*args, **kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(monitor_module.requests, "get", fake_get)


def test_returns_payload_on_200(monkeypatch, calendar_payload):
    _patch_get(monkeypatch, FakeResponse(200, calendar_payload))
    assert NintendoMuseumMonitor().fetch_calendar(2026, 12) == calendar_payload


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_statuses_raise_transient(monkeypatch, status):
    _patch_get(monkeypatch, FakeResponse(status, text="busy"))
    with pytest.raises(TransientFetchError):
        NintendoMuseumMonitor().fetch_calendar(2026, 12)


@pytest.mark.parametrize("status", [401, 403])
def test_blocked_statuses_raise_fatal(monkeypatch, status):
    _patch_get(monkeypatch, FakeResponse(status, text="denied"))
    with pytest.raises(FatalFetchError):
        NintendoMuseumMonitor().fetch_calendar(2026, 12)


def test_network_error_raises_transient(monkeypatch):
    _patch_get(monkeypatch, OSError("connection reset"))
    with pytest.raises(TransientFetchError):
        NintendoMuseumMonitor().fetch_calendar(2026, 12)


def test_unparseable_body_raises_fatal(monkeypatch):
    _patch_get(monkeypatch, FakeResponse(200, None, text="<html>nope</html>"))
    with pytest.raises(FatalFetchError):
        NintendoMuseumMonitor().fetch_calendar(2026, 12)


def test_missing_calendar_key_raises_fatal(monkeypatch):
    _patch_get(monkeypatch, FakeResponse(200, {"data": {}}))
    with pytest.raises(FatalFetchError):
        NintendoMuseumMonitor().fetch_calendar(2026, 12)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_fetch.py -v`
Expected: FAIL — cannot import `TransientFetchError`.

- [ ] **Step 3: Replace the body of `src/monitor.py`**

The file currently holds the Discord webhook class, the proxy plumbing, the `monitor()` loop, and its own `main()`. Replace the whole file with:

```python
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
```

Note: `except Exception` around the request is intentionally broad — `curl_cffi` raises its own error types, and every failure to *reach* the host is retryable.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_fetch.py tests/test_availability.py -v`
Expected: 16 passed (11 in `test_fetch.py` — the two parametrized cases expand to
5 and 2 — plus the 5 from `test_availability.py`).

- [ ] **Step 5: Commit**

```bash
git add src/monitor.py tests/test_fetch.py
git commit -m "feat: classify fetch failures as transient or fatal"
```

---

### Task 6: `src/state.py` — config+state document

**Files:**
- Create: `src/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces:
  - `DEFAULT_PATH = pathlib.Path("state.json")`
  - `class MalformedStateError(Exception)`
  - `load(path=DEFAULT_PATH) -> dict` — the whole document, validated.
  - `target_months(document: dict) -> list[str]`
  - `available(document: dict) -> set[str]`
  - `save_available(document: dict, new_available: set[str], path=DEFAULT_PATH) -> None` — writes the document with `state.available` replaced by the sorted list, leaving `config` untouched.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_state.py`:

```python
import json

import pytest

from src.state import (
    MalformedStateError,
    available,
    load,
    save_available,
    target_months,
)


def write(tmp_path, document):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(document))
    return path


def test_reads_config_and_state(tmp_path):
    path = write(tmp_path, {
        "config": {"target_months": ["2026-12"]},
        "state": {"available": ["2026-12-15"]},
    })
    document = load(path)
    assert target_months(document) == ["2026-12"]
    assert available(document) == {"2026-12-15"}


def test_missing_state_section_reads_as_empty(tmp_path):
    path = write(tmp_path, {"config": {"target_months": ["2026-12"]}})
    assert available(load(path)) == set()


def test_save_preserves_unrelated_config_keys(tmp_path):
    path = write(tmp_path, {
        "config": {"target_months": ["2026-12"], "note": "keep me"},
        "state": {"available": []},
    })
    document = load(path)
    save_available(document, {"2026-12-16", "2026-12-15"}, path)

    written = json.loads(path.read_text())
    assert written["config"] == {"target_months": ["2026-12"], "note": "keep me"}
    assert written["state"]["available"] == ["2026-12-15", "2026-12-16"]


def test_save_never_writes_a_timestamp(tmp_path):
    path = write(tmp_path, {
        "config": {"target_months": ["2026-12"]},
        "state": {"available": []},
    })
    save_available(load(path), set(), path)
    written = json.loads(path.read_text())
    assert set(written["state"].keys()) == {"available"}


def test_repeated_save_of_same_set_is_byte_identical(tmp_path):
    """Guards the 'only commit when it really changed' property."""
    path = write(tmp_path, {
        "config": {"target_months": ["2026-12"]},
        "state": {"available": []},
    })
    save_available(load(path), {"2026-12-15"}, path)
    first = path.read_bytes()
    save_available(load(path), {"2026-12-15"}, path)
    assert path.read_bytes() == first


def test_malformed_json_raises(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    with pytest.raises(MalformedStateError):
        load(path)


def test_missing_target_months_raises(tmp_path):
    path = write(tmp_path, {"config": {}, "state": {"available": []}})
    with pytest.raises(MalformedStateError):
        target_months(load(path))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.state'`

- [ ] **Step 3: Implement**

Create `src/state.py`:

```python
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
```

Sorting is what makes a repeated save byte-identical, which is what lets the workflow's `git diff --cached --quiet` correctly detect "nothing changed".

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_state.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/state.py tests/test_state.py
git commit -m "feat: add config+state json document handling"
```

---

### Task 7: `src/notifier.py` — Gmail SMTP notification

**Files:**
- Create: `src/notifier.py`
- Test: `tests/test_notifier.py`

**Interfaces:**
- Produces:
  - `class EmailConfigError(Exception)`
  - `send_availability_email(new_dates: set[str], smtp_factory=None) -> None` — sends exactly one message listing every date. `smtp_factory` is a no-argument callable returning an object supporting the `smtplib.SMTP` context-manager protocol (`__enter__`, `starttls`, `login`, `send_message`, `__exit__`); tests inject a fake. Reads `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `NOTIFY_EMAIL_TO` from the environment and raises `EmailConfigError` if any is missing.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_notifier.py`:

```python
import pytest

from src.notifier import send_availability_email


class FakeSMTP:
    def __init__(self):
        self.started_tls = False
        self.login_args = None
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, message):
        self.messages.append(message)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "sender@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-password")
    monkeypatch.setenv("NOTIFY_EMAIL_TO", "me@example.com")


def test_sends_one_message_listing_every_date(env):
    fake = FakeSMTP()
    send_availability_email({"2026-12-16", "2026-12-15"}, smtp_factory=lambda: fake)

    assert len(fake.messages) == 1
    message = fake.messages[0]
    body = message.get_content()
    assert "2026-12-15" in body and "2026-12-16" in body
    assert body.index("2026-12-15") < body.index("2026-12-16")
    assert message["To"] == "me@example.com"
    assert message["From"] == "sender@gmail.com"
    assert "2" in message["Subject"]


def test_starts_tls_and_logs_in(env):
    fake = FakeSMTP()
    send_availability_email({"2026-12-15"}, smtp_factory=lambda: fake)
    assert fake.started_tls is True
    assert fake.login_args == ("sender@gmail.com", "app-password")


def test_no_dates_sends_nothing(env):
    fake = FakeSMTP()
    send_availability_email(set(), smtp_factory=lambda: fake)
    assert fake.messages == []


@pytest.mark.parametrize("missing", ["GMAIL_USER", "GMAIL_APP_PASSWORD", "NOTIFY_EMAIL_TO"])
def test_missing_secret_raises(env, monkeypatch, missing):
    monkeypatch.delenv(missing)
    with pytest.raises(EmailConfigError):
        send_availability_email({"2026-12-15"}, smtp_factory=lambda: FakeSMTP())


def test_secret_value_never_appears_in_error(env, monkeypatch):
    monkeypatch.delenv("NOTIFY_EMAIL_TO")
    with pytest.raises(EmailConfigError) as caught:
        send_availability_email({"2026-12-15"}, smtp_factory=lambda: FakeSMTP())
    assert "app-password" not in str(caught.value)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_notifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.notifier'`

- [ ] **Step 3: Implement**

Create `src/notifier.py`:

```python
import os
import smtplib
from email.message import EmailMessage

from utils.logging_setter import setup_logger

logger = setup_logger("nintendo_notifier", "nintendo_notifier.log")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
BOOKING_URL = "https://museum-tickets.nintendo.com/en/calendar"


class EmailConfigError(Exception):
    """A required email environment variable is missing."""


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise EmailConfigError(f"environment variable {name} is not set")
    return value


def _build_message(new_dates: list[str], sender: str, recipient: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"Nintendo Museum: {len(new_dates)} new date(s) available"
    message["From"] = sender
    message["To"] = recipient
    lines = [
        "Newly available Nintendo Museum ticket dates:",
        "",
        *(f"  - {date}" for date in new_dates),
        "",
        f"Book here: {BOOKING_URL}",
    ]
    message.set_content("\n".join(lines))
    return message


def send_availability_email(new_dates: set[str], smtp_factory=None) -> None:
    """Send one email listing every newly available date. No dates, no email."""
    if not new_dates:
        return

    sender = _require("GMAIL_USER")
    password = _require("GMAIL_APP_PASSWORD")
    recipient = _require("NOTIFY_EMAIL_TO")

    message = _build_message(sorted(new_dates), sender, recipient)
    factory = smtp_factory or (lambda: smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30))

    with factory() as smtp:
        smtp.starttls()
        smtp.login(sender, password)
        smtp.send_message(message)

    logger.info("Sent availability email for %d date(s)", len(new_dates))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_notifier.py -v`
Expected: 7 passed (the parametrized missing-secret case expands to 3).

- [ ] **Step 5: Commit**

```bash
git add src/notifier.py tests/test_notifier.py
git commit -m "feat: add gmail smtp availability notifier"
```

---

### Task 8: `main.py` — single-shot orchestration

**Files:**
- Modify: `main.py` (replace entirely)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `src.monitor.NintendoMuseumMonitor`, `src.monitor.available_dates`, `src.monitor.TransientFetchError`, `src.monitor.FatalFetchError`, `src.months.parse_month`, `src.months.is_fully_elapsed`, `src.state.{load, target_months, available, save_available, MalformedStateError}`, `src.notifier.send_availability_email`
- Produces: `run(path=None, today=None, monitor=None, sender=None) -> int` (each argument
  defaults to `None` and is resolved inside the function; `path` falls back to
  `src.state.DEFAULT_PATH`) — the exit code. Injectable arguments exist for tests; `main()` calls `run()` with none and passes the result to `sys.exit`.

Exit-code contract from the spec:
- `0` — success, or a transient fetch failure, or every configured month already elapsed
- `1` — fatal fetch failure (401/403/bad body), malformed `state.json`, or email failure

State is written only when every configured month fetched successfully **and** any required email already succeeded.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_main.py`:

```python
import json
from datetime import date

import pytest

from main import run
from src.monitor import FatalFetchError, TransientFetchError

TODAY = date(2026, 12, 10)


@pytest.fixture
def state_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "config": {"target_months": ["2026-12"]},
        "state": {"available": []},
    }))
    return path


class FakeMonitor:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def fetch_calendar(self, year, month):
        self.calls.append((year, month))
        if self.error:
            raise self.error
        return self.payload


class RecordingSender:
    def __init__(self, error=None):
        self.error = error
        self.sent = []

    def __call__(self, dates):
        if self.error:
            raise self.error
        self.sent.append(set(dates))


def read_available(path):
    return json.loads(path.read_text())["state"]["available"]


def test_first_run_emails_all_and_writes_state(state_file, calendar_payload):
    sender = RecordingSender()
    code = run(path=state_file, today=TODAY,
               monitor=FakeMonitor(calendar_payload), sender=sender)

    assert code == 0
    assert sender.sent == [{"2026-12-15", "2026-12-16"}]
    assert read_available(state_file) == ["2026-12-15", "2026-12-16"]


def test_second_run_with_no_change_sends_nothing(state_file, calendar_payload):
    run(path=state_file, today=TODAY, monitor=FakeMonitor(calendar_payload),
        sender=RecordingSender())
    sender = RecordingSender()
    code = run(path=state_file, today=TODAY,
               monitor=FakeMonitor(calendar_payload), sender=sender)

    assert code == 0
    assert sender.sent == []


def test_shrinking_availability_is_recorded_without_email(state_file, calendar_payload):
    """A sold-out date must leave state, or it can never re-notify."""
    run(path=state_file, today=TODAY, monitor=FakeMonitor(calendar_payload),
        sender=RecordingSender())

    calendar_payload["data"]["calendar"].pop("2026-12-16")
    sender = RecordingSender()
    code = run(path=state_file, today=TODAY,
               monitor=FakeMonitor(calendar_payload), sender=sender)

    assert code == 0
    assert sender.sent == []
    assert read_available(state_file) == ["2026-12-15"]


def test_reopened_date_notifies_again(state_file, calendar_payload):
    full = json.loads(json.dumps(calendar_payload))
    reduced = json.loads(json.dumps(calendar_payload))
    reduced["data"]["calendar"].pop("2026-12-16")

    run(path=state_file, today=TODAY, monitor=FakeMonitor(full), sender=RecordingSender())
    run(path=state_file, today=TODAY, monitor=FakeMonitor(reduced), sender=RecordingSender())

    sender = RecordingSender()
    run(path=state_file, today=TODAY, monitor=FakeMonitor(full), sender=sender)
    assert sender.sent == [{"2026-12-16"}]


def test_transient_fetch_failure_exits_zero_without_writing(state_file):
    sender = RecordingSender()
    code = run(path=state_file, today=TODAY,
               monitor=FakeMonitor(error=TransientFetchError("503")), sender=sender)

    assert code == 0
    assert sender.sent == []
    assert read_available(state_file) == []


def test_fatal_fetch_failure_exits_nonzero_without_writing(state_file):
    code = run(path=state_file, today=TODAY,
               monitor=FakeMonitor(error=FatalFetchError("403 blocked")),
               sender=RecordingSender())

    assert code == 1
    assert read_available(state_file) == []


def test_email_failure_exits_nonzero_and_does_not_advance_state(state_file, calendar_payload):
    code = run(path=state_file, today=TODAY, monitor=FakeMonitor(calendar_payload),
               sender=RecordingSender(error=RuntimeError("smtp down")))

    assert code == 1
    assert read_available(state_file) == [], "state must not advance if the email failed"


def test_elapsed_month_exits_zero(tmp_path, calendar_payload):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "config": {"target_months": ["2026-11"]},
        "state": {"available": []},
    }))
    monitor = FakeMonitor(calendar_payload)
    code = run(path=path, today=date(2027, 1, 5), monitor=monitor, sender=RecordingSender())

    assert code == 0
    assert monitor.calls == [], "an elapsed month must not be fetched"


def test_malformed_state_exits_nonzero(tmp_path, calendar_payload):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    code = run(path=path, today=TODAY, monitor=FakeMonitor(calendar_payload),
               sender=RecordingSender())
    assert code == 1


def test_fetches_every_configured_month(tmp_path, calendar_payload):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "config": {"target_months": ["2026-12", "2027-01"]},
        "state": {"available": []},
    }))
    monitor = FakeMonitor(calendar_payload)
    run(path=path, today=TODAY, monitor=monitor, sender=RecordingSender())
    assert monitor.calls == [(2026, 12), (2027, 1)]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_main.py -v`
Expected: FAIL — `ImportError: cannot import name 'run' from 'main'`

- [ ] **Step 3: Replace `main.py` entirely**

```python
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
from src.months import is_fully_elapsed, parse_month
from src.notifier import send_availability_email
from src.state import MalformedStateError
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
        months = state_module.target_months(document)
    except MalformedStateError as exc:
        logger.error("Cannot read %s: %s", path, exc)
        return EXIT_FAILURE

    live_months = [m for m in months if not is_fully_elapsed(m, today)]
    if not live_months:
        logger.warning(
            "Every configured target month has fully elapsed (%s). Nothing to check — "
            "update config.target_months in %s.", ", ".join(months), path,
        )
        return EXIT_OK

    current: set[str] = set()
    for month in live_months:
        year, month_number = parse_month(month)
        try:
            payload = monitor.fetch_calendar(year, month_number)
        except TransientFetchError as exc:
            logger.warning("Transient fetch failure, leaving state untouched: %s", exc)
            return EXIT_OK
        except FatalFetchError as exc:
            logger.error("Fatal fetch failure: %s", exc)
            return EXIT_FAILURE
        current |= available_dates(payload, today)

    previous = state_module.available(document)
    newly_available = current - previous
    logger.info(
        "Checked %s: %d available, %d newly available",
        ", ".join(live_months), len(current), len(newly_available),
    )

    if newly_available:
        try:
            sender(newly_available)
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
```

Note the ordering: the email is sent *before* `save_available`, so a failed send leaves the previous state on disk and the next run retries the same notification.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -v`
Expected: all tests pass, 10 of them in `test_main.py`.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: single-shot orchestration with spec exit-code contract"
```

---

### Task 9: Remove Discord and proxy support

`src/monitor.py` was already rewritten in Task 5 without them; this removes the now-unreferenced files, the dependency, and the stale configuration.

**Files:**
- Delete: `utils/discord_utils.py`, `utils/load_proxies.py`
- Modify: `pyproject.toml`, `.env.example`

- [ ] **Step 1: Confirm nothing references them**

Run: `uv run rg -n 'discord|load_proxies|proxies|MONITOR_INTERVAL|webhook' --glob '!docs/**' --glob '!*.lock' -i .`
Expected: hits only in `pyproject.toml`, `.env.example`, `README.md`, and `.gitignore` — all four are cleaned up later in this task. **If anything in `src/`, `main.py`, or `tests/` still matches, stop and fix that first.**

- [ ] **Step 2: Delete the files**

```bash
git rm utils/discord_utils.py utils/load_proxies.py
```

`utils/load_proxies.py` contained a `while True:` wrapped in a bare `except: pass` that would hang forever with a bad Webshare key — on a 5-minute schedule that would have pinned a runner until the 6-hour timeout on every run.

- [ ] **Step 3: Drop the dependency and fix metadata**

In `pyproject.toml`: remove the `"discord-webhook>=1.4.1",` line from `dependencies`, and update the description and keywords:

```toml
description = "Automated monitor for Nintendo Museum ticket availability with email notifications"
keywords = ["nintendo", "museum", "ticket", "monitor", "email", "automation"]
```

- [ ] **Step 4: Replace `.env.example`**

```
# Gmail credentials for notifications (app password, NOT your account password)
GMAIL_USER=you@gmail.com
GMAIL_APP_PASSWORD=your_16_char_app_password

# Where to send availability notifications
NOTIFY_EMAIL_TO=you@example.com
```

- [ ] **Step 5: Update `README.md`**

The README documents Discord webhook setup and the continuous-loop usage, all of
which is now wrong. Rewrite the affected sections to describe: the three Gmail
secrets, `state.json`'s `config.target_months`, that the schedule is GitHub
Actions rather than `MONITOR_INTERVAL`, and the `*/5` best-effort caveat. Remove
every reference to Discord, webhooks, proxies, and Webshare.

Run `uv run rg -n 'discord|webhook|proxy|proxies|webshare|MONITOR_INTERVAL' -i README.md`
and confirm it returns nothing before moving on.

- [ ] **Step 6: Re-lock, verify the suite still passes**

Run: `uv sync && uv run pytest -v`
Expected: all tests pass. `discord-webhook` no longer appears in `uv.lock`.

- [ ] **Step 7: Commit**

```bash
git add -A pyproject.toml uv.lock .env.example utils/ README.md
git commit -m "refactor: remove discord and proxy support"
```

---

### Task 10: `state.json`, the `.gitignore` fix, and the real workflow

**Files:**
- Create: `state.json`, `.github/workflows/monitor.yml`
- Modify: `.gitignore`
- Delete: `.github/workflows/probe.yml`

- [ ] **Step 1: Fix `.gitignore`**

`.gitignore:49` is `*.json`, which silently ignores `state.json`. Add the negation immediately **after** that line — order matters, a negation before the pattern has no effect:

```
# Project specific
utils/proxies.txt
data/
*.json
!state.json
```

- [ ] **Step 2: Prove the fix works**

Run: `git check-ignore -v state.json`
Expected: **no output, exit status 1.** If it still prints a `.gitignore:49:*.json` line, the negation is in the wrong place.

- [ ] **Step 3: Create `state.json`**

Set the month you actually want to watch. Per the design survey, tickets open roughly three months out.

```json
{
  "config": {
    "target_months": ["2026-12"]
  },
  "state": {
    "available": []
  }
}
```

- [ ] **Step 4: Create the workflow**

Create `.github/workflows/monitor.yml`:

```yaml
name: Ticket Monitor

on:
  schedule:
    - cron: "*/5 * * * *"
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: ticket-monitor
  cancel-in-progress: false

jobs:
  check:
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - run: uv sync --frozen

      - name: Check ticket availability
        env:
          GMAIL_USER: ${{ secrets.GMAIL_USER }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          NOTIFY_EMAIL_TO: ${{ secrets.NOTIFY_EMAIL_TO }}
        run: uv run main.py

      - name: Commit state if it changed
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add state.json
          if git diff --cached --quiet; then
            echo "State unchanged, nothing to commit."
          else
            git commit -m "Update ticket availability state"
            git pull --rebase --autostash
            git push
          fi
```

`timeout-minutes: 5` prevents a stuck run from holding the slot while new runs fire every 5 minutes. `git pull --rebase --autostash` covers a human pushing between checkout and push.

- [ ] **Step 5: Delete the throwaway probe**

```bash
git rm .github/workflows/probe.yml
```

- [ ] **Step 6: Verify locally against a scratch state file**

**Do not run `main.run()` with no arguments here.** It defaults to the real
`state.json` you just created, which would send the first-run email now and write
~24 dates to disk — leaving nothing for Task 11 Step 3 to verify. Task 11 would
then show a green job, no email, and no commit, which looks identical to a broken
monitor.

Use a scratch copy instead:

```bash
uv run pytest -v
cp state.json /tmp/probe-state.json
uv run python -c "
import main, pathlib
print('exit code:', main.run(path=pathlib.Path('/tmp/probe-state.json')))
"
```

Expected: tests pass; the run prints `exit code: 0`; one real email arrives
listing the available December dates (this needs the three Gmail variables in a
local `.env`); and `/tmp/probe-state.json` — **not** the repo's `state.json` —
now lists those dates.

- [ ] **Step 6b: Confirm the repo's state file is still pristine**

Run: `git diff --stat state.json && cat state.json`

Expected: no diff, and `state.available` is still `[]`. If it is populated, the
local run wrote to the wrong file — reset it to `[]` before committing, or
Task 11's first-run verification cannot work.

- [ ] **Step 7: Commit**

```bash
git add -A .gitignore state.json .github/
git commit -m "feat: add scheduled monitor workflow and initial state"
```

The committed `state.available` must be `[]` so that the first scheduled or
manual run is a genuine first run.

---

### Task 11: End-to-end validation on GitHub

No code changes. This is the spec's manual validation sequence.

- [ ] **Step 0: Note the repository is PUBLIC**

`mike-mike-mike-mike-mike/nintendo-museum-ticket` is public, so `state.json` and
its commit history are world-readable. That is fine for ticket dates, which carry
nothing sensitive, but confirm no personal data is ever added to the `config`
section — the recipient address stays in the `NOTIFY_EMAIL_TO` secret and must
not be moved into `state.json` for convenience.

- [ ] **Step 1: Add the repository secrets**

`gh secret set GMAIL_USER`, `gh secret set GMAIL_APP_PASSWORD`, `gh secret set NOTIFY_EMAIL_TO`.

The Gmail app password requires 2FA on the account and is not the account password.

- [ ] **Step 2: Push and trigger manually**

```bash
git push
gh workflow run "Ticket Monitor"
gh run watch
```

- [ ] **Step 3: Verify the first run**

Expected: job succeeds; the email arrives listing the available December dates; a `Update ticket availability state` commit appears with a populated `state.available`.

- [ ] **Step 4: Verify the second run does not duplicate**

Run: `gh workflow run "Ticket Monitor"` and watch.
Expected: job succeeds, **no** email, log says `0 newly available`, and **no** new commit.

- [ ] **Step 5: Verify state does not advance on failure**

Temporarily set the `NOTIFY_EMAIL_TO` secret to an invalid value, force a new date into play by removing one entry from `state.available` and pushing, then trigger a run.

Expected: the job **fails**, and `state.json` on the default branch is unchanged. Restore the secret afterward.

- [ ] **Step 6: Let the schedule take over**

Confirm runs appear on their own. Expect slippage: GitHub's `*/5` cron is best-effort and routinely runs 10–30 minutes late, and can be skipped entirely during platform incidents.

- [ ] **Step 7: Report to the user**

Include: whether the email arrived, the commit cadence observed, and the actual schedule slippage — the last one tells you whether Actions is good enough or whether the premise needs revisiting.
