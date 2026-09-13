import pytest

from src.retry import RetryableError, with_retry


class FlakyCall:
    """Raises the queued errors in order, then returns a fixed value."""

    def __init__(self, errors, result="ok"):
        self.errors = list(errors)
        self.result = result
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.result


def test_returns_result_on_first_success():
    call = FlakyCall(errors=[])
    assert with_retry(call) == "ok"
    assert call.calls == 1


def test_retries_until_success():
    call = FlakyCall(errors=[RetryableError("1"), RetryableError("2")])
    assert with_retry(call) == "ok"
    assert call.calls == 3


def test_raises_after_exhausting_retries():
    call = FlakyCall(errors=[RetryableError("1"), RetryableError("2"), RetryableError("3")])
    with pytest.raises(RetryableError):
        with_retry(call, retries=3)
    assert call.calls == 3


def test_non_retryable_error_propagates_without_retrying():
    call = FlakyCall(errors=[ValueError("not retryable")])
    with pytest.raises(ValueError):
        with_retry(call)
    assert call.calls == 1


def test_respects_custom_retries_count():
    call = FlakyCall(errors=[RetryableError("1")])
    with pytest.raises(RetryableError):
        with_retry(call, retries=1)
    assert call.calls == 1


def test_respects_custom_retryable_errors():
    call = FlakyCall(errors=[KeyError("boom")])
    assert with_retry(call, retryable_errors=(KeyError,)) == "ok"
    assert call.calls == 2
