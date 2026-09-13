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
