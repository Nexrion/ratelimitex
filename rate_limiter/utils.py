"""
Utility functions for rate limiting.

This module provides helper functions that can be used independently
of the rate limiter classes.
"""

from typing import Any
from .exceptions import RateLimitExceeded

def is_rate_limit_error(error: Any) -> bool:
    """
    Determine if an exception is related to rate limiting.
    
    This function checks various properties of the exception to identify
    if it's likely a rate limit error. It looks for:
    
    1. HTTP 429 status code directly on the error
    2. HTTP 429 status code on error.response
    3. Rate limit related phrases in the error message
    4. Our custom RateLimitExceeded exception
    
    Args:
        error: The exception to check
        
    Returns:
        bool: True if the error appears to be a rate limit error
    """
    # Check for our custom exception first
    if isinstance(error, RateLimitExceeded):
        return True
        
    # Check for status code directly on the error
    if hasattr(error, 'status_code') and error.status_code == 429:
        return True
        
    # Check for status code on error.response
    if hasattr(error, 'response') and hasattr(error.response, 'status_code'):
        if error.response.status_code == 429:
            return True
            
    # Check error message for rate limit related phrases
    error_msg = str(error).lower()
    rate_limit_phrases = [
        'rate limit exceeded',
        'too many requests',
        'quota exceeded',
        'request was throttled',
        'http 429',
        'error 429',
        'rate limit was hit',
        'request throttling',
        'rate exceeded',
        'request limit exceeded',
        'api limit exceeded',
        'rate limiting exceeded',
        'rate-limit exceeded',
        'ratelimit exceeded'
    ]
    
    # Check for exact matches
    return error_msg in rate_limit_phrases
