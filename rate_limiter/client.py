from typing import Dict, Any, Optional, Callable, TypeVar, Awaitable
from .core import RateLimiter
from .models import RateLimitConfig, RateLimitStrategy, RateLimiterStats
from .utils import is_rate_limit_error

# Type variable for generic return type
T = TypeVar('T')

# Global configuration
_global_config = RateLimitConfig()

def configure(
    max_requests: Optional[int] = None,
    time_window: Optional[int] = None,
    strategy: Optional[RateLimitStrategy] = None,
    burst_size: Optional[int] = None,
    burst_window: Optional[int] = None,
    cooldown_period: Optional[int] = None,
    extract_headers_callback: Optional[Callable[[Any], Dict[str, str]]] = None
) -> None:
    """
    Configure default rate limiting parameters for the entire application.
    
    Example:
        ```python
        from rate_limiter import configure
        
        # Set default to 200 requests per minute
        configure(max_requests=200, time_window=60)
        ```
    
    Args:
        max_requests: Maximum number of requests in the time window
        time_window: Time window in seconds
        strategy: Rate limiting strategy (STRICT, BURST, ADAPTIVE)
        burst_size: Maximum burst size (for BURST strategy)
        burst_window: Burst window in seconds (for BURST strategy)
        cooldown_period: Cooldown period after burst in seconds (for BURST strategy)
        extract_headers_callback: Custom callback to extract headers from responses
    """
    global _global_config
    
    if max_requests is not None:
        _global_config.max_requests = max_requests
    if time_window is not None:
        _global_config.time_window = time_window
    if strategy is not None:
        _global_config.strategy = strategy
    if burst_size is not None:
        _global_config.burst_size = burst_size
    if burst_window is not None:
        _global_config.burst_window = burst_window
    if cooldown_period is not None:
        _global_config.cooldown_period = cooldown_period
    if extract_headers_callback is not None:
        _global_config.extract_headers_callback = extract_headers_callback


class RateLimitedClient:
    """
    A client for rate-limited API calls.
    
    Note: For most use cases, consider using the decorator approach instead:
    
    ```python
    from rate_limiter import rate_limited
    
    @rate_limited(max_requests=100, time_window=60)
    async def fetch_data():
        return await api_client.get("/data")
    ```
    
    If you need more control, you can use this client directly:
    
    ```python
    from rate_limiter import RateLimitedClient
    
    client = RateLimitedClient()
    response = await client.execute(api_call)
    ```
    """
    def __init__(
        self,
        max_requests: Optional[int] = None,
        time_window: Optional[int] = None,
        strategy: Optional[RateLimitStrategy] = None,
        burst_size: Optional[int] = None,
        burst_window: Optional[int] = None,
        cooldown_period: Optional[int] = None,
        extract_headers_callback: Optional[Callable[[Any], Dict[str, str]]] = None
    ):
        """
        Create a rate-limited client with optional configuration.
        
        Args:
            max_requests: Override default max requests
            time_window: Override default time window
            strategy: Override default strategy
            burst_size: Override default burst size
            burst_window: Override default burst window
            cooldown_period: Override default cooldown period
            extract_headers_callback: Custom function to extract headers from responses
        """
        # Make a copy of the global config
        config = _global_config.model_copy()
        
        # Apply overrides
        if max_requests is not None:
            config.max_requests = max_requests
        if time_window is not None:
            config.time_window = time_window
        if strategy is not None:
            config.strategy = strategy
        if burst_size is not None:
            config.burst_size = burst_size
        if burst_window is not None:
            config.burst_window = burst_window
        if cooldown_period is not None:
            config.cooldown_period = cooldown_period
        if extract_headers_callback is not None:
            config.extract_headers_callback = extract_headers_callback
            
        self._limiter = RateLimiter(config)
    
    async def __aenter__(self):
        """Used for the context manager approach (less common)"""
        await self._limiter.acquire()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Used for the context manager approach (less common)"""
        if exc_type is not None and exc_val is not None:
            self.update_from_error(exc_val)
    
    async def execute(self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        """
        Execute a function with rate limiting and automatic error handling.
        
        This is the main method used by the decorators and handles all rate limit
        logic automatically including response processing and error handling.
        
        Args:
            func: The async function to execute
            *args: Positional arguments to pass to the function
            **kwargs: Keyword arguments to pass to the function
            
        Returns:
            The result of the function call
        """
        max_retries = 3
        retry_count = 0
        last_error = None
        
        while retry_count < max_retries:
            try:
                # Acquire permission to make the request
                await self._limiter.acquire()
                
                # Call the function
                result = await func(*args, **kwargs)
                
                # Update rate limiter based on response
                self.update_from_response(result)
                
                # Return the result
                return result
                
            except Exception as e:
                # Update rate limiter based on error
                self.update_from_error(e)
                
                # Store the error
                last_error = e
                
                # Check if this is a rate limit error that we should retry
                if is_rate_limit_error(e):
                    retry_count += 1
                    if retry_count < max_retries:
                        # Let the rate limiter handle the wait time
                        continue
                
                # If not a rate limit error or we've reached max retries, re-raise
                raise
        
        # If we got here, we've exhausted our retries
        if last_error:
            raise last_error
            
        # Should never reach here, but just in case
        raise Exception("Rate limit retry loop exited unexpectedly")
    
    def update_from_response(self, response: Any) -> None:
        """Update rate limit settings based on API response headers"""
        self._limiter.update_from_response(response)
    
    def update_from_error(self, error: Any) -> None:
        """Update rate limit settings based on rate limit error"""
        self._limiter.update_from_error(error)
    
    def with_options(
        self,
        max_requests: Optional[int] = None,
        time_window: Optional[int] = None,
        strategy: Optional[RateLimitStrategy] = None,
        burst_size: Optional[int] = None,
        burst_window: Optional[int] = None,
        cooldown_period: Optional[int] = None,
        extract_headers_callback: Optional[Callable[[Any], Dict[str, str]]] = None
    ) -> 'RateLimitedClient':
        """
        Update the current client with new options for subsequent calls.
        
        This allows changing rate limit parameters for specific operations
        without creating a new client.
        
        Example:
            ```python
            # Apply different limits for specific API endpoints
            client.with_options(max_requests=30).execute(api.get_user)  # Lower limit
            client.with_options(max_requests=300).execute(api.list_items)  # Higher limit
            ```
        
        Returns:
            Self, for method chaining
        """
        # Get a copy of the current configuration
        config = self._limiter.config.model_copy()
        
        # Apply overrides
        if max_requests is not None:
            config.max_requests = max_requests
        if time_window is not None:
            config.time_window = time_window
        if strategy is not None:
            config.strategy = strategy
        if burst_size is not None:
            config.burst_size = burst_size
        if burst_window is not None:
            config.burst_window = burst_window
        if cooldown_period is not None:
            config.cooldown_period = cooldown_period
        if extract_headers_callback is not None:
            config.extract_headers_callback = extract_headers_callback
            
        # Update the limiter with the new configuration
        self._limiter = RateLimiter(config)
        
        # Return self for method chaining
        return self
    
    def get_stats(self) -> RateLimiterStats:
        """Get current rate limit statistics"""
        return self._limiter.get_stats()
