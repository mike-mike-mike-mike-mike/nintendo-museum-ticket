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
