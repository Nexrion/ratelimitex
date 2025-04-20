"""
Data models for rate limiting.

This module contains all the Pydantic models and enums used for 
rate limiting configuration and statistics.
"""

from typing import Optional, Dict, Any, Callable
from enum import Enum, auto
from pydantic import BaseModel, Field, ConfigDict

# Default adaptive rate limit settings
DEFAULT_ADAPTIVE_MULTIPLIER = 0.1  # Initial wait multiplier
MAX_ADAPTIVE_MULTIPLIER = 5.0  # Maximum wait multiplier (5 seconds per excess request)
ADAPTIVE_BACKOFF_FACTOR = 2.0  # How much to increase multiplier on rate limit hits
RATE_LIMIT_EXPIRY_SECONDS = 300  # Time after which rate limit hits are "forgotten" (5 minutes)

class RateLimitStrategy(Enum):
    """Different strategies for handling rate limits"""
    STRICT = auto()  # Never exceed the rate limit
    BURST = auto()   # Allow short bursts above the limit
    ADAPTIVE = auto()  # Dynamically adjust based on API response

class DynamicAdjustments(BaseModel):
    """Model for tracking dynamic rate limit adjustments"""
    
    # Wait time multiplier for adaptive rate limiting
    adaptive_multiplier: float = Field(
        DEFAULT_ADAPTIVE_MULTIPLIER,
        description="Wait time multiplier for excess requests",
        ge=0,
        le=MAX_ADAPTIVE_MULTIPLIER
    )
    
    # Retry-After directive
    retry_after: Optional[int] = Field(
        None,
        description="Seconds to wait before retrying from 'Retry-After' header",
        ge=0
    )
    retry_after_timestamp: Optional[float] = Field(
        None,
        description="Timestamp when retry_after was received"
    )
    
    # Time window adjustments
    time_window: Optional[float] = Field(
        None,
        description="Dynamically adjusted time window in seconds",
        gt=0
    )
    time_window_timestamp: Optional[float] = Field(
        None,
        description="Timestamp when time_window was adjusted"
    )
    
    # Maximum requests adjustments
    max_requests: Optional[int] = Field(
        None,
        description="Dynamically adjusted maximum requests",
        gt=0
    )
    max_requests_timestamp: Optional[float] = Field(
        None,
        description="Timestamp when max_requests was adjusted"
    )
    
    # Remaining requests info
    remaining: Optional[int] = Field(
        None,
        description="Remaining requests before rate limit",
        ge=0
    )
    remaining_timestamp: Optional[float] = Field(
        None,
        description="Timestamp when remaining count was checked"
    )
    
    # Model config
    model_config = ConfigDict(extra="allow")  # Allow additional fields for future extensibility

class RateLimitConfig(BaseModel):
    """Configuration for rate limiting"""
    max_requests: int = Field(
        100, 
        description="Maximum number of requests in the time window",
        gt=0
    )
    time_window: int = Field(
        60, 
        description="Time window in seconds (default: 60 seconds = 1 minute)",
        gt=0
    )
    strategy: RateLimitStrategy = Field(
        RateLimitStrategy.STRICT,
        description="Rate limiting strategy (STRICT, BURST, or ADAPTIVE)"
    )
    burst_size: Optional[int] = Field(
        None, 
        description="Maximum burst size (for BURST strategy)",
        gt=0
    )
    burst_window: Optional[int] = Field(
        None, 
        description="Burst window in seconds (for BURST strategy)",
        gt=0
    )
    cooldown_period: Optional[int] = Field(
        None, 
        description="Cooldown period after burst in seconds",
        ge=0
    )
    extract_headers_callback: Optional[Callable[[Any], Dict[str, str]]] = Field(
        None, 
        description="Callback to extract rate limit info from responses"
    )
    dynamic_adjustments: DynamicAdjustments = Field(
        default_factory=DynamicAdjustments,
        description="Dynamic adaptations for adaptive rate limiting"
    )
    
    # Allow arbitrary callables (like extract_headers_callback) to be used
    model_config = ConfigDict(arbitrary_types_allowed=True)

class RateLimiterStats(BaseModel):
    """Pydantic model representing rate limiter statistics"""
    total_requests: int = Field(description="Total number of requests processed")
    total_wait_time: float = Field(description="Total time spent waiting in seconds")
    max_wait_time: float = Field(description="Maximum wait time encountered in seconds")
    current_rate: float = Field(description="Current request rate in requests per minute")
    current_queue_size: int = Field(description="Current number of requests in the tracking queue")
    rate_limit_hits: int = Field(description="Number of rate limit errors encountered")
    
    # Optional fields that may be present depending on state
    last_dynamic_update: Optional[float] = Field(None, description="Timestamp of last dynamic adaptation")
    dynamic_adjustments: Optional[Dict[str, Any]] = Field(None, description="Dynamic rate limit adjustments")
    last_rate_limit_hit: Optional[float] = Field(None, description="Timestamp of last rate limit hit")
    time_since_last_rate_limit: Optional[float] = Field(None, description="Seconds since last rate limit hit")
    rate_limit_expiry_in: Optional[float] = Field(None, description="Seconds until rate limit tracking expires")
