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


def test_excludes_dates_after_the_configured_range_end(calendar_payload):
    result = available_dates(calendar_payload, TODAY, end=date(2026, 12, 15))
    assert result == {"2026-12-15"}


def test_excludes_dates_before_the_configured_range_start(calendar_payload):
    result = available_dates(calendar_payload, TODAY, start=date(2026, 12, 16))
    assert result == {"2026-12-16"}
