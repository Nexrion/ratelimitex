import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_time():
    """Mock both time.time() and loop time for deterministic tests."""
    current_time = 1000.0

    with patch('time.time') as mock_time_mod:
        with patch('asyncio.get_event_loop') as mock_get_loop:
            # time.time()
            def time_side_effect():
                nonlocal current_time
                return current_time

            mock_time_mod.side_effect = time_side_effect

            # loop.time()
            class _MockLoop:
                def time(self):
                    return current_time

            mock_get_loop.return_value = _MockLoop()

            # Helper to advance time
            def advance(seconds):
                nonlocal current_time
                current_time += seconds
                return current_time

            mock_time_mod.advance = advance
            yield mock_time_mod


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
