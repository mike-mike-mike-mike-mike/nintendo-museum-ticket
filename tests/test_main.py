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
    """fail_times=None means `error` is raised on every call; an int caps
    how many leading calls fail before it starts succeeding."""

    def __init__(self, payload=None, error=None, fail_times=None):
        self.payload = payload
        self.error = error
        self.fail_times = fail_times
        self.calls = []

    def fetch_calendar(self, year, month):
        self.calls.append((year, month))
        if self.error and (self.fail_times is None or len(self.calls) <= self.fail_times):
            raise self.error
        return self.payload


class RecordingSender:
    """fail_times=None means `error` is raised on every call; an int caps
    how many leading calls fail before it starts succeeding."""

    def __init__(self, error=None, fail_times=None):
        self.error = error
        self.fail_times = fail_times
        self.sent = []
        self.attempts = 0

    def __call__(self, dates):
        self.attempts += 1
        if self.error and (self.fail_times is None or self.attempts <= self.fail_times):
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
    monitor = FakeMonitor(error=TransientFetchError("503"))
    code = run(path=state_file, today=TODAY, monitor=monitor, sender=sender)

    assert code == 0
    assert sender.sent == []
    assert read_available(state_file) == []
    assert len(monitor.calls) == 3, "should retry the fetch before giving up"


def test_transient_fetch_recovers_after_retry(state_file, calendar_payload):
    """A fetch that fails once or twice with a transient error and then
    succeeds must behave exactly like a clean first try."""
    sender = RecordingSender()
    monitor = FakeMonitor(calendar_payload, error=TransientFetchError("503"), fail_times=2)
    code = run(path=state_file, today=TODAY, monitor=monitor, sender=sender)

    assert code == 0
    assert len(monitor.calls) == 3
    assert sender.sent == [{"2026-12-15", "2026-12-16"}]
    assert read_available(state_file) == ["2026-12-15", "2026-12-16"]


def test_fatal_fetch_failure_exits_nonzero_without_writing(state_file):
    monitor = FakeMonitor(error=FatalFetchError("403 blocked"))
    code = run(path=state_file, today=TODAY, monitor=monitor, sender=RecordingSender())

    assert code == 1
    assert read_available(state_file) == []
    assert len(monitor.calls) == 1, "a fatal error is not retryable"


def test_email_failure_exits_nonzero_and_does_not_advance_state(state_file, calendar_payload):
    sender = RecordingSender(error=RuntimeError("smtp down"))
    code = run(path=state_file, today=TODAY, monitor=FakeMonitor(calendar_payload), sender=sender)

    assert code == 1
    assert read_available(state_file) == [], "state must not advance if the email failed"
    assert sender.attempts == 3, "should retry sending before giving up"


def test_email_recovers_after_retry(state_file, calendar_payload):
    sender = RecordingSender(error=RuntimeError("smtp down"), fail_times=2)
    code = run(path=state_file, today=TODAY, monitor=FakeMonitor(calendar_payload), sender=sender)

    assert code == 0
    assert sender.attempts == 3
    assert sender.sent == [{"2026-12-15", "2026-12-16"}]
    assert read_available(state_file) == ["2026-12-15", "2026-12-16"]


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


def test_malformed_target_month_exits_nonzero_without_raising(tmp_path, calendar_payload):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "config": {"target_months": ["2026-1"]},
        "state": {"available": []},
    }))
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
