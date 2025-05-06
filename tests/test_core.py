import pytest
import asyncio
import time
from rate_limiter.core import RateLimiter
from rate_limiter.models import RateLimitConfig, RateLimitStrategy

def test_rate_limiter_initialization():
    """Test that RateLimiter can be initialized with default config."""
    limiter = RateLimiter()
    assert isinstance(limiter.config, RateLimitConfig)
    assert limiter.config.max_requests > 0
    assert limiter.config.time_window > 0

def test_rate_limiter_custom_config():
    """Test that RateLimiter can be initialized with custom config."""
    config = RateLimitConfig(
        max_requests=10,
        time_window=60,
        strategy=RateLimitStrategy.ADAPTIVE
    )
    limiter = RateLimiter(config=config)
    assert limiter.config.max_requests == 10
    assert limiter.config.time_window == 60
    assert limiter.config.strategy == RateLimitStrategy.ADAPTIVE

@pytest.mark.asyncio
async def test_rate_limiter_acquire():
    """Test the acquire method of RateLimiter."""
    limiter = RateLimiter(RateLimitConfig(max_requests=2, time_window=1))
    
    # First request should be allowed
    await limiter.acquire()
    assert limiter.total_requests == 1
    assert limiter.total_wait_time == 0
    
    # Second request should be allowed (within same time window)
    await limiter.acquire()
    assert limiter.total_requests == 2
    assert limiter.total_wait_time == 0
    
    # Wait for time window to reset
    await asyncio.sleep(1.1)
    
    # Third request should be allowed (new time window)
    await limiter.acquire()
    assert limiter.total_requests == 3
    assert limiter.total_wait_time == 0
    
    # Fourth request should be allowed (same time window)
    await limiter.acquire()
    assert limiter.total_requests == 4
    assert limiter.total_wait_time == 0
    
    # Fifth request should be blocked (will wait)
    await limiter.acquire()
    assert limiter.total_requests == 5
    assert limiter.total_wait_time > 0

@pytest.mark.asyncio
async def test_rate_limiter_different_keys():
    """Test that different keys have independent rate limits."""
    # Use a longer time window to ensure requests aren't cleaned up too quickly
    config = RateLimitConfig(
        max_requests=1,
        time_window=5,  # 5 seconds window
        strategy=RateLimitStrategy.STRICT
    )
    limiter = RateLimiter(config)

    # First key should be allowed
    await limiter.acquire("key1")
    assert limiter.total_requests == 1
    assert limiter.total_wait_time == 0

    # Second key should also be allowed (independent limit)
    await limiter.acquire("key2")
    assert limiter.total_requests == 2
    assert limiter.total_wait_time == 0

    # First key should now be blocked (exceeds its limit)
    await limiter.acquire("key1")
    assert limiter.total_requests == 3
    assert limiter.total_wait_time > 0
    initial_wait_time = limiter.total_wait_time

    # Second key should still be independent
    # Even though key1 had to wait, key2's limit is separate
    await limiter.acquire("key2")
    assert limiter.total_requests == 4
    # Wait time shouldn't change because key2's limit is independent of key1
    assert limiter.total_wait_time == initial_wait_time

    # After waiting, old requests should be cleaned up
    # Each key should only have its most recent request
    assert len(limiter.requests["key1"]) == 1
    assert len(limiter.requests["key2"]) == 1
    