from datetime import date

import pytest

from src.date_range import months_spanned, parse_range


def test_parse_range_splits_start_and_end():
    assert parse_range({"start_date": "2026-12-01", "end_date": "2027-01-15"}) == (
        date(2026, 12, 1),
        date(2027, 1, 15),
    )


def test_parse_range_rejects_malformed_values():
    bad_values = [
        {},
        {"start_date": "2026-12-01"},
        {"end_date": "2027-01-15"},
        {"start_date": "2026-12-01", "end_date": "not-a-date"},
        {"start_date": "not-a-date", "end_date": "2027-01-15"},
        {"start_date": "2027-01-15", "end_date": "2026-12-01"},
        "2026-12-01",
        None,
    ]
    for bad in bad_values:
        with pytest.raises(ValueError):
            parse_range(bad)


def test_months_spanned_within_a_single_month():
    assert months_spanned(date(2026, 12, 1), date(2026, 12, 20)) == [(2026, 12)]


def test_months_spanned_across_multiple_months():
    assert months_spanned(date(2026, 12, 20), date(2027, 2, 5)) == [
        (2026, 12),
        (2027, 1),
        (2027, 2),
    ]
