"""
Utility functions for rate limiting.

This module provides helper functions that can be used independently
of the rate limiter classes.
"""


def is_rate_limit_error(error: Exception) -> bool:
    """
    Determine if an exception is related to rate limiting.
    
    This function checks various properties of the exception to identify
    if it's likely a rate limit error. It looks for:
    
    1. HTTP 429 status code directly on the error
    2. HTTP 429 status code on error.response
    3. Rate limit related phrases in the error message
    
    Args:
        error: The exception to check
        
    Returns:
        True if the error appears to be a rate limit error, False otherwise
        
    Examples:
        ```python
        try:
            response = await api_client.get("/endpoint")
        except Exception as e:
            if is_rate_limit_error(e):
                print("Hit a rate limit, waiting before retry...")
                await asyncio.sleep(30)
                # Then retry
            else:
                # Handle other errors
                raise
        ```
    """
    # Check for status codes
    if hasattr(error, 'status_code') and error.status_code == 429:
        return True
        
    # Check for response attribute with status_code
    if hasattr(error, 'response') and hasattr(error.response, 'status_code') and error.response.status_code == 429:
        return True
        
    # Check error message
    error_str = str(error).lower()
    rate_limit_phrases = ['rate limit', 'ratelimit', 'too many requests', '429', 'retry after', 'throttle']
    return any(phrase in error_str for phrase in rate_limit_phrases)
