import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_time():
    """Fixture to mock time.time() for deterministic tests."""
    current_time = 1000.0  # Start with a non-zero value

    with patch('time.time') as mock:

        def side_effect():
            nonlocal current_time
            return current_time

        # Allow tests to advance time
        def advance(seconds):
            nonlocal current_time
            current_time += seconds
            return current_time

        mock.side_effect = side_effect
        mock.advance = advance
        yield mock


@pytest.fixture
def mock_sleep():
    """Fixture to mock asyncio.sleep to avoid actual waiting in tests."""
    with patch('asyncio.sleep', new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def mock_api_client():
    """Fixture for a simple mock API client that can be rate limited."""

    class MockAPIClient:
        def __init__(self):
            self.call_count = 0
            self.requests = []
            self.should_raise_rate_limit = False
            self.headers = {}

        async def get(self, endpoint, params=None):
            self.call_count += 1
            self.requests.append((time.time(), endpoint, params))

            if self.should_raise_rate_limit:
                error = Exception('Rate limit exceeded')
                error.status_code = 429
                error.headers = self.headers
                raise error

            response = MagicMock()
            response.headers = self.headers
            return response

    return MockAPIClient()


@pytest.fixture
def mock_response_headers():
    """Fixture providing mock rate limit headers."""
    return {
        'x-ratelimit-limit': '100',
        'x-ratelimit-remaining': '50',
        'x-ratelimit-reset': '300',
        'retry-after': '30',
    }


@pytest.fixture
def rate_limit_error():
    """Fixture providing a mock rate limit error."""
    error = Exception('Rate limit exceeded')
    error.status_code = 429
    error.headers = {'retry-after': '30'}
    return error


@pytest.fixture
def mock_headers_callback():
    """Fixture providing a callback for extracting headers."""

    def extract_headers(response):
        # Extract headers from response object (which might have different interfaces)
        if hasattr(response, 'headers'):
            return {k.lower(): v for k, v in response.headers.items()}
        return {}

    return extract_headers
