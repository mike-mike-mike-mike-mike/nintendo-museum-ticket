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
