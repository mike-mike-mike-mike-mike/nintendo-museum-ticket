class RetryableError(Exception):
    """Indicates a transient error that can be retried."""

def with_retry(func, retries=3, retryable_errors=(RetryableError,)):
    for attempt in range(retries):
        try:
            return func()
        except retryable_errors:
            if attempt == retries - 1:
                raise
