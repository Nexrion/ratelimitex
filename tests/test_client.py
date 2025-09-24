import pytest

from ratelimitex.client import RateLimitedClient, configure
from ratelimitex.models import RateLimiterStats, RateLimitStrategy


@pytest.mark.asyncio
class TestRateLimitedClient:
    async def test_execute_success(self, mock_api_client, mock_time, mock_sleep):
        """Test successful execution of a function with rate limiting."""
        client = RateLimitedClient(max_requests=5, time_window=10)

        # Define a mock API call
        async def api_call():
            return await mock_api_client.get('/test')

        # Execute the API call
        await client.execute(api_call)

        # Verify the API was called
        assert mock_api_client.call_count == 1

        # Sleep should not have been called (we're under the limit)
        mock_sleep.assert_not_called()

    async def test_execute_rate_limit_retry(self, mock_api_client, mock_time, mock_sleep):
        """Test automatic retry when a rate limit error occurs."""
        client = RateLimitedClient(
            max_requests=5, time_window=2, strategy=RateLimitStrategy.ADAPTIVE
        )

        # Make the API client raise a rate limit error on first call
        mock_api_client.should_raise_rate_limit = True

        # Define a mock API call that will succeed on second attempt
        async def api_call():
            # Get the current call count
            count = mock_api_client.call_count

            # After the first attempt, stop raising errors
            if count == 1:
                mock_api_client.should_raise_rate_limit = False
                result = await mock_api_client.get('/test')
                return result
            else:
                return await mock_api_client.get('/test')

        # Execute the API call - it should retry automatically
        await client.execute(api_call)

        # Verify the API was called twice (original + retry)
        assert mock_api_client.call_count == 2

        # Sleep should have been called at least once for the retry
        assert mock_sleep.call_count >= 1

    async def test_execute_max_retries_exceeded_adaptive(
        self, mock_api_client, mock_time, mock_sleep
    ):
        """Test that max retries is enforced."""
        client = RateLimitedClient(
            max_requests=5, time_window=10, strategy=RateLimitStrategy.ADAPTIVE
        )

        # Make the API client always raise a rate limit error
        mock_api_client.should_raise_rate_limit = True

        # Define a mock API call
        async def api_call():
            return await mock_api_client.get('/test')

        # Execute the API call - it should retry but eventually fail
        with pytest.raises(Exception, match='Rate limit exceeded'):
            await client.execute(api_call)

        # Verify the API was called the expected number of times (1 + max_retries)
        assert mock_api_client.call_count == 4  # Original + 3 retries

        # Sleep should have been called for each retry
        assert mock_sleep.call_count == 3

    async def test_execute_max_retries_exceeded_strict(
        self, mock_api_client, mock_time, mock_sleep
    ):
        """Test that max retries is enforced."""
        client = RateLimitedClient(
            max_requests=5, time_window=10, strategy=RateLimitStrategy.STRICT
        )

        # Make the API client always raise a rate limit error
        mock_api_client.should_raise_rate_limit = True

        # Define a mock API call
        async def api_call():
            return await mock_api_client.get('/test')

        # Execute the API call - it should retry but eventually fail
        with pytest.raises(Exception, match='Rate limit exceeded'):
            await client.execute(api_call)

        # Verify the API was called the expected number of times (1 + max_retries)
        assert mock_api_client.call_count == 4  # Original + 3 retries

        # We should not wait on retry in STRICT mode
        assert mock_sleep.call_count == 0

    async def test_context_manager(self, mock_api_client, mock_time, mock_sleep):
        """Test using the client as a context manager."""
        client = RateLimitedClient(max_requests=5, time_window=10)

        # Use the client as a context manager
        async with client:
            # Do something that would normally need rate limiting
            await mock_api_client.get('/test')

        # Verify the API was called
        assert mock_api_client.call_count == 1

        # Sleep should not have been called (we're under the limit)
        mock_sleep.assert_not_called()

    async def test_context_manager_with_error(self, mock_api_client, mock_time, mock_sleep):
        """Test context manager properly handles errors."""
        client = RateLimitedClient(
            max_requests=5, time_window=10, strategy=RateLimitStrategy.ADAPTIVE
        )

        # Make the API client raise a rate limit error
        mock_api_client.should_raise_rate_limit = True

        # Use the client as a context manager with an error
        with pytest.raises(Exception, match='Rate limit exceeded'):
            async with client:
                await mock_api_client.get('/test')

        # Verify the error was processed for rate limiting
        stats = client.get_stats()
        assert stats.rate_limit_hits >= 1

    async def test_update_from_response(self, mock_api_client, mock_time, mock_response_headers):
        """Test updating rate limit settings from a response."""
        client = RateLimitedClient(
            max_requests=5, time_window=10, strategy=RateLimitStrategy.ADAPTIVE
        )

        # Add rate limit headers to the response
        mock_api_client.headers = mock_response_headers

        # Define a mock API call
        async def api_call():
            return await mock_api_client.get('/test')

        # Execute the API call
        await client.execute(api_call)

        # Get stats to check if dynamic adjustments were made
        stats = client.get_stats()

        # The dynamic adjustments should exist
        assert stats.dynamic_adjustments is not None

    async def test_update_from_error(self, mock_api_client, mock_time, rate_limit_error):
        """Test updating rate limit settings from an error."""
        client = RateLimitedClient(
            max_requests=5, time_window=10, strategy=RateLimitStrategy.ADAPTIVE
        )

        # Manually update from an error
        client.update_from_error(rate_limit_error)

        # Get stats to check if the error was recorded
        stats = client.get_stats()

        # The rate limit hit should be recorded
        assert stats.rate_limit_hits == 1
        assert stats.last_rate_limit_hit is not None

    async def test_with_options(self, mock_time):
        """Test creating a new client with modified options."""
        client = RateLimitedClient(
            max_requests=5, time_window=10, strategy=RateLimitStrategy.STRICT
        )

        # Create a new client with different options
        new_client = client.with_options(max_requests=10, strategy=RateLimitStrategy.BURST)

        # Verify the new client has the updated options
        _stats = new_client.get_stats()

        # The original client should be unchanged
        assert client._limiter.config.max_requests == 5
        assert client._limiter.config.strategy == RateLimitStrategy.STRICT

        # The new client should have the new options
        assert new_client._limiter.config.max_requests == 10
        assert new_client._limiter.config.strategy == RateLimitStrategy.BURST
        # Time window should be the same as original
        assert new_client._limiter.config.time_window == 10

    async def test_get_stats(self, mock_api_client, mock_time, mock_sleep):
        """Test getting statistics from the client."""
        client = RateLimitedClient(max_requests=5, time_window=10)

        # Define a mock API call
        async def api_call():
            return await mock_api_client.get('/test')

        # Execute several API calls
        for _i in range(3):
            await client.execute(api_call)
            mock_time.advance(1)  # Advance time between calls

        # Get stats
        stats = client.get_stats()

        # Check stats
        assert isinstance(stats, RateLimiterStats)
        assert stats.total_requests == 3
        assert stats.current_queue_size == 3  # All requests still in the window
        assert stats.rate_limit_hits == 0
        assert stats.current_rate > 0  # Should have a positive request rate


class TestGlobalConfig:
    def test_configure(self):
        """Test setting the global configuration."""
        # Reset to default by re-importing
        from importlib import reload

        from ratelimitex import client

        reload(client)

        # Configure global settings
        configure(
            max_requests=1000,
            time_window=120,
            strategy=RateLimitStrategy.BURST,
            burst_size=2000,
            burst_window=30,
            cooldown_period=60,
        )

        # Create a client with no options - should use global settings
        client = RateLimitedClient()

        # Verify the client has the global settings
        assert client._limiter.config.max_requests == 1000
        assert client._limiter.config.time_window == 120
        assert client._limiter.config.strategy == RateLimitStrategy.BURST
        assert client._limiter.config.burst_size == 2000
        assert client._limiter.config.burst_window == 30
        assert client._limiter.config.cooldown_period == 60

    def test_client_override(self):
        """Test that client settings override global settings."""
        # Configure global settings
        configure(max_requests=1000, time_window=120, strategy=RateLimitStrategy.BURST)

        # Create a client with custom options
        client = RateLimitedClient(max_requests=500, strategy=RateLimitStrategy.STRICT)

        # Verify the client has the custom settings
        assert client._limiter.config.max_requests == 500
        assert client._limiter.config.strategy == RateLimitStrategy.STRICT
        # Should still use global setting for time_window
        assert client._limiter.config.time_window == 120
