import pytest
import asyncio
import time
from rate_limiter.decorators import rate_limited, adaptive_rate_limited, burst_rate_limited
from rate_limiter.models import RateLimitConfig, RateLimitStrategy
from rate_limiter.exceptions import RateLimitExceeded

@pytest.mark.asyncio
async def test_rate_limited_decorator():
    """Test the basic rate_limited decorator."""
    @rate_limited(max_requests=2, time_window=1)
    async def test_function():
        return "success"
    
    # First two calls should succeed immediately
    assert await test_function() == "success"
    assert await test_function() == "success"
    
    # Third call should be delayed due to rate limiting
    start_time = time.time()
    result = await test_function()
    end_time = time.time()
    
    # Should still succeed but with a delay
    assert result == "success"
    assert end_time - start_time >= 0.5  # Should have waited at least 0.5 seconds
    
    # Get stats to verify rate limiting behavior
    stats = test_function.get_stats()
    assert stats.total_wait_time > 0  # Should have waited some time
    assert stats.max_wait_time > 0  # Should have recorded maximum wait time

@pytest.mark.asyncio
async def test_rate_limited_decorator_prevention():
    """Test that the rate_limited decorator properly prevents requests when rate limit is exceeded."""
    request_count = 0
    
    @rate_limited(max_requests=2, time_window=1)
    async def test_function():
        nonlocal request_count
        request_count += 1
        return "success"
    
    # First two calls should succeed and increment request_count
    assert await test_function() == "success"
    assert await test_function() == "success"
    assert request_count == 2
    
    # Third call should be delayed but still increment request_count
    start_time = asyncio.get_event_loop().time()
    result = await test_function()
    end_time = asyncio.get_event_loop().time()
    assert result == "success"
    assert request_count == 3
    assert end_time - start_time >= 0.5
    
    # Fourth call should succeed immediately since we've waited
    start_time = asyncio.get_event_loop().time()
    result = await test_function()
    end_time = asyncio.get_event_loop().time()
    assert result == "success"
    assert request_count == 4
    assert end_time - start_time < 0.5  # Should not have waited
    
    # Get stats to verify rate limiting behavior
    stats = test_function.get_stats()
    assert stats.total_wait_time > 0  # Should have waited at least once
    assert stats.max_wait_time > 0  # Should have recorded maximum wait time
    assert stats.rate_limit_hits >= 1  # Should have hit rate limit at least once

@pytest.mark.asyncio
async def test_adaptive_rate_limited_decorator():
    """Test the adaptive_rate_limited decorator."""
    @adaptive_rate_limited(max_requests=2, time_window=1)
    async def test_function():
        return "success"
    
    # First two calls should succeed immediately
    assert await test_function() == "success"
    assert await test_function() == "success"
    
    # Third call should be delayed due to rate limiting
    start_time = asyncio.get_event_loop().time()
    result = await test_function()
    end_time = asyncio.get_event_loop().time()
    
    # Should still succeed but with a delay
    assert result == "success"
    assert end_time - start_time >= 0.5  # Should have waited at least 0.5 seconds
    
    # Get stats to verify adaptive behavior
    stats = test_function.get_stats()
    assert stats.rate_limit_hits > 0  # Should have recorded rate limit hits
    assert stats.total_wait_time > 0  # Should have waited some time

@pytest.mark.asyncio
async def test_burst_rate_limited_decorator():
    """Test the burst_rate_limited decorator."""
    request_count = 0
    
    @burst_rate_limited(max_requests=2, time_window=1, burst_size=3, burst_window=1)
    async def test_function():
        nonlocal request_count
        request_count += 1
        return "success"
    
    # First three calls should succeed immediately (burst)
    assert await test_function() == "success"
    assert await test_function() == "success"
    assert await test_function() == "success"
    assert request_count == 3
    
    # Fourth call should be delayed due to rate limiting
    start_time = asyncio.get_event_loop().time()
    result = await test_function()
    end_time = asyncio.get_event_loop().time()
    assert result == "success"
    assert request_count == 4
    assert end_time - start_time >= 0.5  # Should have waited at least 0.5 seconds
    
    # Fifth call should succeed immediately since we've waited
    start_time = asyncio.get_event_loop().time()
    result = await test_function()
    end_time = asyncio.get_event_loop().time()
    assert result == "success"
    assert request_count == 5
    assert end_time - start_time < 0.5  # Should not have waited
    
    # Get stats to verify rate limiting behavior
    stats = test_function.get_stats()
    assert stats.total_wait_time > 0  # Should have waited at least once
    assert stats.max_wait_time > 0  # Should have recorded maximum wait time
    assert stats.rate_limit_hits >= 1  # Should have hit rate limit at least once

@pytest.mark.asyncio
async def test_decorator_with_custom_config():
    """Test decorators with custom RateLimitConfig."""
    request_count = 0
    
    config = RateLimitConfig(
        max_requests=2,
        time_window=1,
        strategy=RateLimitStrategy.STRICT
    )
    
    @rate_limited(max_requests=config.max_requests, time_window=config.time_window, strategy=config.strategy)
    async def test_function():
        nonlocal request_count
        request_count += 1
        return "success"
    
    # First two calls should succeed immediately
    assert await test_function() == "success"
    assert await test_function() == "success"
    assert request_count == 2
    
    # Third call should be delayed due to rate limiting
    start_time = time.time()
    result = await test_function()
    end_time = time.time()
    assert result == "success"
    assert request_count == 3
    assert end_time - start_time >= 0.5  # Should have waited at least 0.5 seconds
    
    # Get stats to verify rate limiting behavior
    stats = test_function.get_stats()
    assert stats.total_wait_time > 0  # Should have waited some time
    assert stats.max_wait_time > 0  # Should have recorded maximum wait time
    assert stats.rate_limit_hits > 0  # Should have recorded rate limit hits
