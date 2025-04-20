"""
Rate Limiter module for managing API rate limits with a simple DX.
"""

from .core import RateLimiter
from .models import RateLimitConfig, RateLimitStrategy, RateLimiterStats
from .client import RateLimitedClient, configure
from .decorators import rate_limited, adaptive_rate_limited, burst_rate_limited
from .utils import is_rate_limit_error

__all__ = [
    'RateLimitedClient',
    'configure',
    'RateLimiter',
    'RateLimitConfig', 
    'RateLimitStrategy',
    'RateLimiterStats',
    'rate_limited',
    'adaptive_rate_limited',
    'burst_rate_limited',
    'is_rate_limit_error',
]
