import asyncio
import time
import logging
import re
from typing import Optional, List, Dict, Any
from .models import (
    RateLimitStrategy, 
    RateLimitConfig, 
    RateLimiterStats, 
    
    # Constants
    DEFAULT_ADAPTIVE_MULTIPLIER,
    MAX_ADAPTIVE_MULTIPLIER,
    ADAPTIVE_BACKOFF_FACTOR,
    RATE_LIMIT_EXPIRY_SECONDS
)

logger = logging.getLogger(__name__)

# Common rate limit header patterns
RATE_LIMIT_HEADERS = [
    # Standard headers
    'x-rate-limit-reset',
    'x-rate-limit-remaining', 
    'x-rate-limit-limit',
    'x-rate-limit-seconds',
    'x-ratelimit-reset',
    'x-ratelimit-remaining',
    'x-ratelimit-limit',
    # GitHub-style
    'x-ratelimit-reset',
    # Twitter-style
    'x-rate-limit-reset',
    # AWS-style
    'x-amzn-ratelimit-limit',
    # Generic retry header
    'retry-after'
]

# Regex to extract numeric values from headers
HEADER_VALUE_PATTERN = re.compile(r'(\d+)')

class RateLimiter:
    """
    Rate limiter with simplified interface but powerful capabilities under the hood.
    
    For most use cases, use the RateLimitedClient instead of using this class directly.
    """
    
    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config or RateLimitConfig()
        self.requests: List[float] = []
        self.burst_requests: List[float] = []
        self._lock = asyncio.Lock()
        
        # Statistics
        self.total_requests: int = 0
        self.total_wait_time: float = 0
        self.max_wait_time: float = 0
        self.rate_limit_hits: int = 0
        self.last_dynamic_update: Optional[float] = None
        self.last_rate_limit_hit: Optional[float] = None
        
        # Validate configuration
        if self.config.strategy == RateLimitStrategy.BURST:
            if not self.config.burst_size or not self.config.burst_window:
                self.config.burst_size = self.config.max_requests * 2
                self.config.burst_window = 10  # 10 seconds
            if self.config.burst_size < self.config.max_requests:
                self.config.burst_size = self.config.max_requests
    
    async def acquire(self) -> None:
        """
        Acquire permission to make a request, waiting if necessary.
        """
        async with self._lock:
            now = time.time()
            self._cleanup_old_requests(now)
            
            # Check if any rate limit hits should be expired
            self._check_rate_limit_expiry(now)
            
            if self._should_wait(now):
                wait_time = self._calculate_wait_time(now)
                if wait_time > 0:
                    logger.debug(f"Rate limit reached, waiting for {wait_time:.2f} seconds")
                    self.total_wait_time += wait_time
                    self.max_wait_time = max(self.max_wait_time, wait_time)
                    await asyncio.sleep(wait_time)
                    self._cleanup_old_requests(time.time())
            
            self._record_request(now)
    
    def _check_rate_limit_expiry(self, now: float) -> None:
        """Check if rate limit hit tracking should be reset due to time passing"""
        if self.last_rate_limit_hit is not None:
            # If it's been long enough since the last rate limit hit, reset tracking
            if now - self.last_rate_limit_hit > RATE_LIMIT_EXPIRY_SECONDS:
                logger.info(f"Rate limit hit tracking expired after {RATE_LIMIT_EXPIRY_SECONDS} seconds")
                self.last_rate_limit_hit = None
                
                # Also reset the adaptive multiplier to default if no recent rate limits
                if self.config.strategy == RateLimitStrategy.ADAPTIVE:
                    # Keep track of the old value for logging
                    old_multiplier = self.config.dynamic_adjustments.adaptive_multiplier
                    
                    # Only reset if it's above the default
                    if old_multiplier > DEFAULT_ADAPTIVE_MULTIPLIER:
                        self.config.dynamic_adjustments.adaptive_multiplier = DEFAULT_ADAPTIVE_MULTIPLIER
                        logger.info(f"Resetting adaptive multiplier from {old_multiplier:.2f} to {DEFAULT_ADAPTIVE_MULTIPLIER:.2f}")
    
    def update_from_response(self, response: Any) -> None:
        """
        Update rate limit settings based on API response headers.
        
        This is used by the ADAPTIVE strategy to dynamically adjust
        based on actual API responses.
        
        Args:
            response: The API response object
        """
        if self.config.strategy != RateLimitStrategy.ADAPTIVE:
            return
        
        headers = {}
        # Use custom callback if provided
        if self.config.extract_headers_callback is not None:
            headers = self.config.extract_headers_callback(response)
        # Otherwise try to extract headers directly
        elif hasattr(response, 'headers'):
            headers = {k.lower(): v for k, v in response.headers.items()}
        
        self._process_rate_limit_headers(headers)
    
    def update_from_error(self, error: Any) -> None:
        """
        Update rate limit settings based on rate limit error.
        
        Args:
            error: The error object
        """
        if self.config.strategy != RateLimitStrategy.ADAPTIVE:
            return
            
        # Record this as a rate limit hit
        now = time.time()
        self.rate_limit_hits += 1
        self.last_rate_limit_hit = now
        
        # Increase the adaptive multiplier when we hit a rate limit
        current_multiplier = self.config.dynamic_adjustments.adaptive_multiplier
        new_multiplier = min(current_multiplier * ADAPTIVE_BACKOFF_FACTOR, MAX_ADAPTIVE_MULTIPLIER)
        self.config.dynamic_adjustments.adaptive_multiplier = new_multiplier
        logger.info(f"Rate limit hit, increasing wait multiplier to {new_multiplier:.2f} seconds per excess request")

        # Try to extract headers from the error
        headers = {}
        
        # Extract from response attribute if it exists
        if hasattr(error, 'response') and hasattr(error.response, 'headers'):
            headers = {k.lower(): v for k, v in error.response.headers.items()}
        
        # Extract from headers attribute if it exists
        elif hasattr(error, 'headers'):
            headers = {k.lower(): v for k, v in error.headers.items()}
            
        # Extract from string representation as last resort
        else:
            error_str = str(error)
            # Look for common patterns like "retry after 30 seconds"
            retry_match = re.search(r'retry after (\d+)', error_str.lower())
            if retry_match:
                headers['retry-after'] = retry_match.group(1)
                
        self._process_rate_limit_headers(headers)
        
    def _process_rate_limit_headers(self, headers: Dict[str, str]) -> None:
        """
        Process rate limit headers and update settings accordingly.
        
        Args:
            headers: The response headers
        """
        now = time.time()
        has_updated = False
        
        # Normalize header keys to lowercase
        headers = {k.lower(): v for k, v in headers.items()}
        
        # Extract rate limit information
        reset_time = None
        limit = None
        remaining = None
        retry_after = None
        
        # Check for Retry-After header (direct seconds to wait)
        if 'retry-after' in headers:
            try:
                retry_after = int(headers['retry-after'])
                logger.info(f"Found Retry-After header: {retry_after} seconds")
                has_updated = True
                
                # Record this adaptation
                self.config.dynamic_adjustments.retry_after = retry_after
                self.config.dynamic_adjustments.retry_after_timestamp = now
            except (ValueError, TypeError):
                pass
        
        # Check for rate limit headers
        for header in RATE_LIMIT_HEADERS:
            if header in headers:
                value = headers[header]
                # Extract numeric value
                match = HEADER_VALUE_PATTERN.search(str(value))
                if match:
                    value = int(match.group(1))
                    
                    if 'reset' in header:
                        # Handle both epoch timestamps and seconds-from-now
                        if value > now + 3600:  # If it's more than an hour in the future, it's likely an epoch
                            reset_time = value
                        else:
                            reset_time = now + value
                    elif 'limit' in header and 'remaining' not in header:
                        limit = value
                    elif 'remaining' in header:
                        remaining = value
        
        # Update time window based on reset time
        if reset_time is not None:
            time_until_reset = max(0, reset_time - now)
            if time_until_reset > 0:
                logger.info(f"Updating time window to {time_until_reset:.1f} seconds based on reset header")
                self.config.time_window = time_until_reset
                has_updated = True
                
                # Record this adaptation
                self.config.dynamic_adjustments.time_window = time_until_reset
                self.config.dynamic_adjustments.time_window_timestamp = now
        
        # Update rate limit based on limit header
        if limit is not None:
            logger.info(f"Updating max requests to {limit} based on limit header")
            self.config.max_requests = limit
            has_updated = True
            
            # Record this adaptation
            self.config.dynamic_adjustments.max_requests = limit
            self.config.dynamic_adjustments.max_requests_timestamp = now
        
        # Force wait if we know remaining is 0 or very low
        if remaining is not None and remaining <= 5 and reset_time is not None:
            time_until_reset = max(0, reset_time - now)
            if time_until_reset > 0:
                logger.warning(f"Only {remaining} requests remaining, waiting for reset in {time_until_reset:.1f} seconds")
                # Implemented in the calling code
                
                # Record this situation
                self.config.dynamic_adjustments.remaining = remaining
                self.config.dynamic_adjustments.remaining_timestamp = now
        
        # Set last update time if any adaptation happened
        if has_updated:
            self.last_dynamic_update = now

    def _cleanup_old_requests(self, now: float) -> None:
        """Remove requests older than the time window"""
        self.requests = [req_time for req_time in self.requests 
                        if now - req_time < self.config.time_window]
        if self.config.strategy == RateLimitStrategy.BURST:
            self.burst_requests = [req_time for req_time in self.burst_requests 
                                 if now - req_time < self.config.burst_window]
    
    def _should_wait(self, now: float) -> bool:
        """Determine if we need to wait based on the current strategy"""
        if self.config.strategy == RateLimitStrategy.STRICT:
            return len(self.requests) >= self.config.max_requests
        
        elif self.config.strategy == RateLimitStrategy.BURST:
            if len(self.burst_requests) >= self.config.burst_size:
                return True
            if len(self.requests) >= self.config.max_requests:
                return True
            return False
        
        elif self.config.strategy == RateLimitStrategy.ADAPTIVE:
            # Get threshold based on past rate limit hits
            threshold_multiplier = 1.0
            
            # If we've hit rate limits recently, be more conservative
            if self.last_rate_limit_hit and now - self.last_rate_limit_hit < 60:  # Within last minute
                threshold_multiplier = 0.9  # Lower threshold to 90% of max
            
            # In adaptive mode, we start slowing down as we approach the limit
            return len(self.requests) >= (self.config.max_requests * threshold_multiplier)
        
        return False
    
    def _calculate_wait_time(self, now: float) -> float:
        """Calculate how long to wait based on the current strategy"""
        if not self.requests:
            return 0
            
        if self.config.strategy == RateLimitStrategy.STRICT:
            return max(0, self.requests[0] + self.config.time_window - now)
        
        elif self.config.strategy == RateLimitStrategy.BURST:
            if len(self.burst_requests) >= self.config.burst_size:
                # After a burst, enforce a cooldown period
                if self.config.cooldown_period:
                    return self.config.cooldown_period
                return max(0, self.burst_requests[0] + self.config.burst_window - now)
            return max(0, self.requests[0] + self.config.time_window - now)
        
        elif self.config.strategy == RateLimitStrategy.ADAPTIVE:
            # First: Check if we have a retry-after directive that's still valid
            if self.config.dynamic_adjustments.retry_after is not None and self.config.dynamic_adjustments.retry_after_timestamp is not None:
                retry_after = self.config.dynamic_adjustments.retry_after
                retry_timestamp = self.config.dynamic_adjustments.retry_after_timestamp
                # Use this if it's not too old (within last minute)
                if now - retry_timestamp < 60:
                    adjusted_retry = retry_after - (now - retry_timestamp)
                    if adjusted_retry > 0:
                        return adjusted_retry
            
            # Get current adaptive multiplier (with default if not set)
            multiplier = self.config.dynamic_adjustments.adaptive_multiplier
            
            # Calculate excess requests
            excess = len(self.requests) - self.config.max_requests
            
            # If we've had rate limit hits recently, apply a minimum wait time
            min_wait = 0
            if self.last_rate_limit_hit and now - self.last_rate_limit_hit < 120:  # Within last 2 minutes
                # Calculate minimum wait based on recency and severity of last hit
                recency_factor = max(0, 1 - ((now - self.last_rate_limit_hit) / 120))
                min_wait = recency_factor * 1.0  # Up to 1 second minimum wait
            
            # Return maximum of calculated wait time and minimum wait
            return max(min_wait, excess * multiplier)
        
        return 0
    
    def _record_request(self, now: float) -> None:
        """Record a new request"""
        self.requests.append(now)
        if self.config.strategy == RateLimitStrategy.BURST:
            self.burst_requests.append(now)
        self.total_requests += 1
    
    def reset_rate_limit_tracking(self) -> None:
        """
        Manually reset rate limit tracking.
        
        This resets the rate limit hit counter and adaptive settings back to defaults.
        Useful when you know the rate limits have been reset (e.g., after acquiring a new API key).
        """
        self.last_rate_limit_hit = None
        
        # Reset adaptive settings if using adaptive strategy
        if self.config.strategy == RateLimitStrategy.ADAPTIVE:
            old_multiplier = self.config.dynamic_adjustments.adaptive_multiplier
            if old_multiplier != DEFAULT_ADAPTIVE_MULTIPLIER:
                logger.info(f"Manually resetting adaptive multiplier from {old_multiplier:.2f} to {DEFAULT_ADAPTIVE_MULTIPLIER:.2f}")
                self.config.dynamic_adjustments.adaptive_multiplier = DEFAULT_ADAPTIVE_MULTIPLIER
        
        logger.info("Rate limit tracking manually reset")
    
    def get_stats(self) -> RateLimiterStats:
        """Get current rate limit statistics"""
        now = time.time()
        window_start = now - self.config.time_window
        recent_requests = len([req for req in self.requests if req > window_start])
        current_rate = recent_requests / (self.config.time_window / 60)  # requests per minute
        
        stats = {
            "total_requests": self.total_requests,
            "total_wait_time": self.total_wait_time,
            "max_wait_time": self.max_wait_time,
            "current_rate": current_rate,
            "current_queue_size": len(self.requests),
            "rate_limit_hits": self.rate_limit_hits,
        }
        
        # Add dynamic adaptations if any
        if self.last_dynamic_update is not None:
            stats["last_dynamic_update"] = self.last_dynamic_update
            stats["dynamic_adjustments"] = self.config.dynamic_adjustments.model_dump(exclude_none=True)
            
        # Add last rate limit hit if any
        if self.last_rate_limit_hit is not None:
            stats["last_rate_limit_hit"] = self.last_rate_limit_hit
            stats["time_since_last_rate_limit"] = now - self.last_rate_limit_hit
            stats["rate_limit_expiry_in"] = max(0, RATE_LIMIT_EXPIRY_SECONDS - (now - self.last_rate_limit_hit))
            
        return RateLimiterStats(**stats)
