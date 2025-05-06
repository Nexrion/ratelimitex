import pytest
from rate_limiter.exceptions import RateLimitExceeded
from rate_limiter.utils import is_rate_limit_error


def test_is_rate_limit_error():
    """Test that is_rate_limit_error correctly identifies rate limit errors."""
    # Test with RateLimitExceeded exception
    assert is_rate_limit_error(RateLimitExceeded()) is True

    # Test with RateLimitExceeded subclass
    class CustomRateLimitError(RateLimitExceeded):
        pass
    assert is_rate_limit_error(CustomRateLimitError()) is True

    # Test with HTTP 429 status code directly
    class HTTP429Error(Exception):
        status_code = 429
    assert is_rate_limit_error(HTTP429Error()) is True

    # Test with HTTP 429 status code in response
    class Response:
        def __init__(self):
            self.status_code = 429
    class ErrorWithResponse(Exception):
        def __init__(self):
            self.response = Response()
    assert is_rate_limit_error(ErrorWithResponse()) is True

    # Test with rate limit phrases in error message
    assert is_rate_limit_error(Exception("Rate limit exceeded")) is True
    assert is_rate_limit_error(Exception("Too many requests")) is True
    assert is_rate_limit_error(Exception("Quota exceeded")) is True
    assert is_rate_limit_error(Exception("Request was throttled")) is True
    assert is_rate_limit_error(Exception("HTTP 429")) is True
    assert is_rate_limit_error(Exception("Error 429")) is True

    # Test with case-insensitive matching
    assert is_rate_limit_error(Exception("RATE LIMIT EXCEEDED")) is True
    assert is_rate_limit_error(Exception("TOO MANY REQUESTS")) is True

    # Test with partial matches
    assert is_rate_limit_error(Exception("Rate limit was hit")) is True
    assert is_rate_limit_error(Exception("Request throttling")) is True

    # Test with non-rate-limit exceptions
    assert is_rate_limit_error(Exception()) is False
    assert is_rate_limit_error(ValueError()) is False
    assert is_rate_limit_error(RuntimeError()) is False

    # Test with non-429 status codes
    class HTTP404Error(Exception):
        status_code = 404
    assert is_rate_limit_error(HTTP404Error()) is False

    # Test with non-rate-limit response status codes
    class Non429Response:
        def __init__(self):
            self.status_code = 404
    class ErrorWithNon429Response(Exception):
        def __init__(self):
            self.response = Non429Response()
    assert is_rate_limit_error(ErrorWithNon429Response()) is False

    # Test with non-rate-limit phrases
    assert is_rate_limit_error(Exception("Not a rate limit error")) is False
    assert is_rate_limit_error(Exception("Invalid request")) is False
    assert is_rate_limit_error(Exception("Server error")) is False
