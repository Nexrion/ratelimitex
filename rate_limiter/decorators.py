import functools
from typing import Optional, Callable, Any, TypeVar, Awaitable

from .client import RateLimitedClient
from .models import RateLimitStrategy, RateLimiterStats

# Type variable for generic return type
T = TypeVar('T')

def rate_limited(
    max_requests: Optional[int] = None,
    time_window: Optional[int] = None,
    strategy: Optional[RateLimitStrategy] = None,
    burst_size: Optional[int] = None,
    burst_window: Optional[int] = None,
    cooldown_period: Optional[int] = None,
    extract_headers_callback: Optional[Callable[[Any], dict]] = None
):
    """
    Decorator that applies rate limiting to an async function.
    
    This decorator creates a RateLimitedClient and uses it to rate-limit calls
    to the decorated function. It handles all retry logic and response processing
    automatically.
    
    Example:
        ```python
        @rate_limited(max_requests=100, time_window=60)
        async def fetch_user(user_id: str):
            return await api_client.get(f"/users/{user_id}")
        
        # Call the function normally - rate limiting is handled automatically
        user = await fetch_user("12345")
        ```
    
    Args:
        max_requests: Maximum number of requests in the time window
        time_window: Time window in seconds
        strategy: Rate limiting strategy (STRICT, BURST, ADAPTIVE)
        burst_size: Maximum burst size (for BURST strategy)
        burst_window: Burst window in seconds (for BURST strategy)
        cooldown_period: Cooldown period after burst in seconds (for BURST strategy)
        extract_headers_callback: Custom callback to extract headers from responses
        
    Returns:
        A decorator function that wraps the given async function
    """
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        # Create a client once per decorated function
        client = RateLimitedClient(
            max_requests=max_requests,
            time_window=time_window,
            strategy=strategy,
            burst_size=burst_size,
            burst_window=burst_window,
            cooldown_period=cooldown_period,
            extract_headers_callback=extract_headers_callback
        )
        
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            # Use the client's execute method to handle rate limiting
            return await client.execute(func, *args, **kwargs)
        
        # Add a reference to the client for stats and configuration
        wrapper.rate_limiter = client
        
        # Allow accessing stats directly from the decorated function
        wrapper.get_stats = client.get_stats
        # Add type annotation for better IDE support
        wrapper.get_stats.__annotations__['return'] = RateLimiterStats
        
        return wrapper
    
    return decorator

def adaptive_rate_limited(
    max_requests: Optional[int] = None,
    time_window: Optional[int] = None,
    extract_headers_callback: Optional[Callable[[Any], dict]] = None
):
    """
    Decorator that applies adaptive rate limiting to an async function.
    
    This is a convenience decorator that sets the strategy to ADAPTIVE.
    
    Example:
        ```python
        @adaptive_rate_limited()
        async def fetch_user(user_id: str):
            return await api_client.get(f"/users/{user_id}")
        ```
    
    Args:
        max_requests: Initial maximum requests per time window (will adapt)
        time_window: Initial time window in seconds (will adapt)
        extract_headers_callback: Custom callback to extract headers from responses
        
    Returns:
        A decorator function that wraps the given async function
    """
    return rate_limited(
        max_requests=max_requests,
        time_window=time_window,
        strategy=RateLimitStrategy.ADAPTIVE,
        extract_headers_callback=extract_headers_callback
    )

def burst_rate_limited(
    max_requests: Optional[int] = None,
    time_window: Optional[int] = None,
    burst_size: Optional[int] = None,
    burst_window: Optional[int] = None,
    cooldown_period: Optional[int] = None
):
    """
    Decorator that applies burst rate limiting to an async function.
    
    This is a convenience decorator that sets the strategy to BURST.
    
    Example:
        ```python
        @burst_rate_limited(max_requests=100, burst_size=150, burst_window=10)
        async def fetch_user(user_id: str):
            return await api_client.get(f"/users/{user_id}")
        ```
    
    Args:
        max_requests: Maximum requests per time window
        time_window: Time window in seconds
        burst_size: Maximum burst size
        burst_window: Burst window in seconds
        cooldown_period: Cooldown period after burst in seconds
        
    Returns:
        A decorator function that wraps the given async function
    """
    return rate_limited(
        max_requests=max_requests,
        time_window=time_window,
        strategy=RateLimitStrategy.BURST,
        burst_size=burst_size,
        burst_window=burst_window,
        cooldown_period=cooldown_period
    )
