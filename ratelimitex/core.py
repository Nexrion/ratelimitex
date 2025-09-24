import asyncio
import logging
import re
import time
from typing import Any, Optional

from .models import (
    ADAPTIVE_BACKOFF_FACTOR,
    # Constants
    DEFAULT_ADAPTIVE_MULTIPLIER,
    MAX_ADAPTIVE_MULTIPLIER,
    RATE_LIMIT_EXPIRY_SECONDS,
    RateLimitConfig,
    RateLimiterStats,
    RateLimitStrategy,
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
    'retry-after',
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
        self.requests: dict[str, list[float]] = {}  # key -> list of request timestamps
        self.burst_requests: dict[str, list[float]] = {}  # key -> list of burst request timestamps
        self.wait_times: dict[str, float] = {}  # key -> total wait time
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

    async def acquire(self, key: str = 'default') -> None:
        """
        Acquire permission to make a request, waiting if necessary.

        Args:
            key: The key to rate limit on. Different keys have independent rate limits.
        """
        async with self._lock:
            # Initialize request lists for this key if they don't exist
            if key not in self.requests:
                self.requests[key] = []
            if key not in self.burst_requests:
                self.burst_requests[key] = []
            if key not in self.wait_times:
                self.wait_times[key] = 0.0

            # Get current time and clean up old requests (use event loop's monotonic clock)
            now = asyncio.get_event_loop().time()
            self._cleanup_old_requests(now, key)

            # Check if we should wait before recording the new request
            if self._should_wait(now, key):
                wait_time = self.calculate_wait_time(now, key)
                if wait_time > 0:
                    logger.debug(
                        f'Rate limit reached for key {key}, waiting for {wait_time:.2f} seconds'
                    )

                    # Release the lock while waiting
                    self._lock.release()
                    try:
                        start_wait = asyncio.get_event_loop().time()
                        await asyncio.sleep(wait_time)
                        actual_wait = asyncio.get_event_loop().time() - start_wait

                        # Only update wait times after we've actually waited
                        self.wait_times[key] += actual_wait  # Accumulate wait time for this key
                        self.total_wait_time += actual_wait  # Accumulate total wait time
                        self.max_wait_time = max(self.max_wait_time, actual_wait)
                        self.rate_limit_hits += 1
                        self.last_rate_limit_hit = now
                    finally:
                        await self._lock.acquire()

                    # Get new time after waiting
                    now = asyncio.get_event_loop().time()

                    # Clean up old requests again after waiting
                    self._cleanup_old_requests(now, key)

            # Record the request
            self._record_request(now, key)

    def _check_rate_limit_expiry(self, now: float) -> None:
        """Check if rate limit hit tracking should be reset due to time passing"""
        if self.last_rate_limit_hit is not None:
            # If it's been long enough since the last rate limit hit, reset tracking
            if now - self.last_rate_limit_hit > RATE_LIMIT_EXPIRY_SECONDS:
                logger.info(
                    f'Rate limit hit tracking expired after {RATE_LIMIT_EXPIRY_SECONDS} seconds'
                )
                self.last_rate_limit_hit = None

                # Also reset the adaptive multiplier to default if no recent rate limits
                if self.config.strategy == RateLimitStrategy.ADAPTIVE:
                    # Keep track of the old value for logging
                    old_multiplier = self.config.dynamic_adjustments.adaptive_multiplier

                    # Only reset if it's above the default
                    if old_multiplier > DEFAULT_ADAPTIVE_MULTIPLIER:
                        self.config.dynamic_adjustments.adaptive_multiplier = (
                            DEFAULT_ADAPTIVE_MULTIPLIER
                        )
                        logger.info(
                            'Resetting adaptive multiplier from '
                            f'{old_multiplier:.2f} to {DEFAULT_ADAPTIVE_MULTIPLIER:.2f}'
                        )

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
        # Record this as a rate limit hit for all strategies
        now = time.time()
        self.rate_limit_hits += 1
        self.last_rate_limit_hit = now

        # Only update adaptive settings if using adaptive strategy
        if self.config.strategy == RateLimitStrategy.ADAPTIVE:
            # Increase the adaptive multiplier when we hit a rate limit
            current_multiplier = self.config.dynamic_adjustments.adaptive_multiplier
            new_multiplier = min(
                current_multiplier * ADAPTIVE_BACKOFF_FACTOR, MAX_ADAPTIVE_MULTIPLIER
            )
            self.config.dynamic_adjustments.adaptive_multiplier = new_multiplier
            logger.info(
                'Rate limit hit, increasing wait multiplier to '
                f'{new_multiplier:.2f} seconds per excess request'
            )

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

    def _process_rate_limit_headers(self, headers: dict[str, str]) -> None:
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
                logger.info(f'Found Retry-After header: {retry_after} seconds')
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
                        if (
                            value > now + 3600
                        ):  # If it's more than an hour in the future, it's likely an epoch
                            reset_time = value
                        else:
                            reset_time = now + value
                    elif 'limit' in header and 'remaining' not in header:
                        limit = value
                    elif 'remaining' in header:
                        remaining = value

        # Update time window based on reset time
        if reset_time is not None:
            time_until_reset = max([0, reset_time - now])
            if time_until_reset > 0:
                logger.info(
                    f'Updating time window to {time_until_reset:.1f} seconds based on reset header'
                )
                self.config.time_window = time_until_reset
                has_updated = True

                # Record this adaptation
                self.config.dynamic_adjustments.time_window = time_until_reset
                self.config.dynamic_adjustments.time_window_timestamp = now

        # Update rate limit based on limit header
        if limit is not None:
            logger.info(f'Updating max requests to {limit} based on limit header')
            self.config.max_requests = limit
            has_updated = True

            # Record this adaptation
            self.config.dynamic_adjustments.max_requests = limit
            self.config.dynamic_adjustments.max_requests_timestamp = now

        # Force wait if we know remaining is 0 or very low
        if remaining is not None and remaining <= 5 and reset_time is not None:
            time_until_reset = max([0, reset_time - now])
            if time_until_reset > 0:
                logger.warning(
                    'Only {remaining} requests remaining, waiting for reset in '
                    f'{time_until_reset:.1f} seconds'
                )
                # Implemented in the calling code

                # Record this situation
                self.config.dynamic_adjustments.remaining = remaining
                self.config.dynamic_adjustments.remaining_timestamp = now

        # Set last update time if any adaptation happened
        if has_updated:
            self.last_dynamic_update = now

    def _cleanup_old_requests(self, now: float, key: str) -> None:
        """Remove requests older than the time window"""
        if key in self.requests:
            window_start = now - self.config.time_window
            # Keep length variable for potential future metrics
            _old_count = len(self.requests[key])
            self.requests[key] = [
                req_time for req_time in self.requests[key] if req_time > window_start
            ]

            # Don't reset wait times during cleanup.

        if key in self.burst_requests and self.config.strategy == RateLimitStrategy.BURST:
            burst_window_start = now - self.config.burst_window
            self.burst_requests[key] = [
                req_time for req_time in self.burst_requests[key] if req_time > burst_window_start
            ]

    def _should_wait(self, now: float, key: str) -> bool:
        """Determine if we need to wait based on the current strategy"""
        if key not in self.requests:
            return False

        # Do not force waiting solely due to a recent rate limit hit; client handles backoff

        if self.config.strategy == RateLimitStrategy.STRICT:
            # Count only requests within the time window
            window_start = now - self.config.time_window
            recent_requests = [req for req in self.requests[key] if req > window_start]
            # Wait if adding this request would exceed the limit
            if len(recent_requests) + 1 > self.config.max_requests:
                # Calculate wait time based on the oldest request in the window
                oldest_request = min(recent_requests)
                wait_time = max([0, oldest_request + self.config.time_window - now])
                if wait_time > 0:
                    return True
            return False

        elif self.config.strategy == RateLimitStrategy.BURST:
            if key not in self.burst_requests:
                self.burst_requests[key] = []

            # Count requests in both windows
            window_start = now - self.config.time_window
            burst_window_start = now - self.config.burst_window

            recent_requests = [req for req in self.requests[key] if req > window_start]
            recent_burst_requests = [
                req for req in self.burst_requests[key] if req > burst_window_start
            ]

            # If we haven't exceeded the burst limit, allow the request
            if len(recent_burst_requests) + 1 <= self.config.burst_size:
                return False

            # If we've exceeded the burst limit, fall back to regular rate limiting
            if len(recent_requests) + 1 > self.config.max_requests:
                # Calculate wait time based on the oldest request in the window
                oldest_request = min(recent_requests)
                wait_time = max([0, oldest_request + self.config.time_window - now])
                if wait_time > 0:
                    return True
            return False

        elif self.config.strategy == RateLimitStrategy.ADAPTIVE:
            # Get threshold based on past rate limit hits
            threshold_multiplier = 1.0

            # If we've hit rate limits recently, be more conservative
            if self.last_rate_limit_hit is not None and now - self.last_rate_limit_hit < 60:
                threshold_multiplier = 0.8  # Lower threshold to 80% of max

            # Count only requests within the time window
            window_start = now - self.config.time_window
            recent_requests = [req for req in self.requests[key] if req > window_start]

            # In adaptive mode, we still enforce the absolute limit
            if len(recent_requests) + 1 > self.config.max_requests:
                # Calculate wait time based on the oldest request in the window
                oldest_request = min(recent_requests)
                wait_time = max([0, oldest_request + self.config.time_window - now])
                if wait_time > 0:
                    return True

            # But we also start slowing down as we approach the limit
            if len(recent_requests) + 1 > (self.config.max_requests * threshold_multiplier):
                # Calculate wait time based on the oldest request in the window
                oldest_request = min(recent_requests)
                wait_time = max([0, oldest_request + self.config.time_window - now])
                if wait_time > 0:
                    return True
            return False

        return False

    def calculate_wait_time(self, now: float, key: str = 'default') -> float:
        """Calculate how long to wait based on the current strategy"""
        if key not in self.requests or not self.requests[key]:
            return 0

        if self.config.strategy == RateLimitStrategy.STRICT:
            # Count requests within the time window
            window_start = now - self.config.time_window
            recent_requests = [req for req in self.requests[key] if req > window_start]

            # Only wait if we've exceeded the rate limit
            if len(recent_requests) + 1 > self.config.max_requests:
                oldest_request = min(recent_requests)
                base_wait = max([0, oldest_request + self.config.time_window - now])
                return max(base_wait, 0.5)  # Always wait at least 0.5 seconds when rate limited
            return 0

        elif self.config.strategy == RateLimitStrategy.BURST:
            # Count requests in both windows
            window_start = now - self.config.time_window
            burst_window_start = now - self.config.burst_window

            recent_requests = [req for req in self.requests[key] if req > window_start]
            recent_burst_requests = [
                req for req in self.burst_requests[key] if req > burst_window_start
            ]

            # If we've exceeded the burst limit, wait based on the regular rate limit
            if len(recent_burst_requests) + 1 > self.config.burst_size:
                if len(recent_requests) + 1 > self.config.max_requests:
                    oldest_request = min(recent_requests)
                    base_wait = max([0, oldest_request + self.config.time_window - now])
                    return max(base_wait, 0.5)  # Always wait at least 0.5 seconds when rate limited
                return 0

            # If we're approaching the burst limit, start waiting
            if len(recent_burst_requests) + 1 > self.config.burst_size * 0.8:  # 80% of burst limit
                if recent_burst_requests:
                    oldest_burst = min(recent_burst_requests)
                    burst_wait = max([0, oldest_burst + self.config.burst_window - now])
                    return max(
                        burst_wait, 0.5
                    )  # Always wait at least 0.5 seconds when rate limited

            return 0

        elif self.config.strategy == RateLimitStrategy.ADAPTIVE:
            # If we've hit a rate limit recently, always wait at least 0.5 seconds
            if self.last_rate_limit_hit is not None and now - self.last_rate_limit_hit < 60:
                return 0.5  # Minimum wait time after rate limit hit

            # First: Check if we have a retry-after directive that's still valid
            if (
                self.config.dynamic_adjustments.retry_after is not None
                and self.config.dynamic_adjustments.retry_after_timestamp is not None
            ):
                retry_after = self.config.dynamic_adjustments.retry_after
                retry_timestamp = self.config.dynamic_adjustments.retry_after_timestamp
                # Use this if it's not too old (within last minute)
                if now - retry_timestamp < 60:
                    adjusted_retry = retry_after - (now - retry_timestamp)
                    if adjusted_retry > 0:
                        return max(
                            adjusted_retry, 0.5
                        )  # Always wait at least 0.5 seconds when rate limited

            # Get current adaptive multiplier (with default if not set)
            multiplier = self.config.dynamic_adjustments.adaptive_multiplier

            # Count only requests within the time window
            window_start = now - self.config.time_window
            recent_requests = [req for req in self.requests[key] if req > window_start]

            # Only wait if we've exceeded the rate limit
            if len(recent_requests) + 1 > self.config.max_requests:
                oldest_request = min(recent_requests)
                base_wait = max([0, oldest_request + self.config.time_window - now])
                excess = len(recent_requests) + 1 - self.config.max_requests
                return max(
                    base_wait + excess * multiplier, 0.5
                )  # Always wait at least 0.5 seconds when rate limited

            # For adaptive strategy, start waiting earlier but with smaller increments
            if len(recent_requests) + 1 > self.config.max_requests * 0.8:  # 80% of limit
                oldest_request = min(recent_requests)
                base_wait = max([0, oldest_request + self.config.time_window - now])
                excess = len(recent_requests) + 1 - int(self.config.max_requests * 0.8)
                return max(
                    base_wait * 0.5 + excess * multiplier * 0.5, 0.5
                )  # Always wait at least 0.5 seconds when rate limited

            return 0

        return 0

    def _record_request(self, now: float, key: str) -> None:
        """Record a new request"""
        if key not in self.requests:
            self.requests[key] = []
        if key not in self.burst_requests:
            self.burst_requests[key] = []
        if key not in self.wait_times:
            self.wait_times[key] = 0.0

        self.requests[key].append(now)
        if self.config.strategy == RateLimitStrategy.BURST:
            self.burst_requests[key].append(now)
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
                logger.info(
                    'Manually resetting adaptive multiplier from '
                    f'{old_multiplier:.2f} to {DEFAULT_ADAPTIVE_MULTIPLIER:.2f}'
                )
                self.config.dynamic_adjustments.adaptive_multiplier = DEFAULT_ADAPTIVE_MULTIPLIER

        logger.info('Rate limit tracking manually reset')

    def get_stats(self) -> RateLimiterStats:
        """Get current rate limit statistics"""
        now = time.time()
        window_start = now - self.config.time_window

        # Count recent requests across all keys
        recent_requests = 0
        total_requests = 0
        for key in self.requests:
            requests_in_window = [req for req in self.requests[key] if req > window_start]
            recent_requests += len(requests_in_window)
            total_requests += len(self.requests[key])

        current_rate = recent_requests / (self.config.time_window / 60)  # requests per minute

        # Use the accumulated total_wait_time instead of recalculating
        stats = {
            'total_requests': self.total_requests,
            'total_wait_time': self.total_wait_time,  # Use the accumulated value
            'max_wait_time': self.max_wait_time,
            'current_rate': current_rate,
            'current_queue_size': total_requests,  # Total number of requests across all keys
            'rate_limit_hits': self.rate_limit_hits,
        }

        # Add dynamic adaptations if any
        if self.last_dynamic_update is not None:
            stats['last_dynamic_update'] = self.last_dynamic_update
            stats['dynamic_adjustments'] = self.config.dynamic_adjustments.model_dump(
                exclude_none=True
            )

        # Add last rate limit hit if any
        if self.last_rate_limit_hit is not None:
            stats['last_rate_limit_hit'] = self.last_rate_limit_hit
            stats['time_since_last_rate_limit'] = now - self.last_rate_limit_hit
            stats['rate_limit_expiry_in'] = max(
                0, RATE_LIMIT_EXPIRY_SECONDS - (now - self.last_rate_limit_hit)
            )

        return RateLimiterStats(**stats)
