# Rate Limiter

An enhanced rate limiter with a simple interface but powerful capabilities under the hood.

## Features

- **Decorator-based rate limiting**
- Simple, intuitive API
- Sensible defaults (100 requests per minute)
- **Built-in automatic error handling and retries**
- Project-wide configuration
- Per-call overrides
- Multiple rate limiting strategies
- Burst handling
- Statistics and monitoring
- Dynamic adaptation based on API response headers

## Rate Limiting Strategies

### Strict Mode (Default)
- Never exceeds the rate limit
- Waits for the full time window when limit is reached
- Best for APIs with strict rate limits

### Burst Mode
- Allows short bursts above the limit
- Configurable burst size and window
- Optional cooldown period after bursts
- Best for APIs that allow occasional bursts

### Adaptive Mode
- Dynamically adjusts based on API response headers
- Adapts to changing rate limits during runtime
- Handles rate limit errors gracefully
- Best for APIs with variable rate limits or multiple environments

## Installation

```bash
pip install rate-limiter
```

## Usage

### Decorator Approach (Recommended)

The simplest way to use the rate limiter is with decorators:

```python
from rate_limiter import rate_limited

# Apply rate limiting to any async function
@rate_limited(max_requests=100, time_window=60)
async def fetch_user(user_id: str):
    return await api_client.get(f"/users/{user_id}")

# Call the function normally - rate limiting is applied automatically
user = await fetch_user("12345")
```

Specialized decorators for different strategies:

```python
from rate_limiter import adaptive_rate_limited, burst_rate_limited

# Adaptive rate limiting (adjusts based on API responses)
@adaptive_rate_limited()
async def fetch_trending():
    return await api_client.get("/trending")

# Burst rate limiting (allows short bursts of higher traffic)
@burst_rate_limited(max_requests=100, burst_size=150, burst_window=10)
async def fetch_comments(post_id: str):
    return await api_client.get(f"/posts/{post_id}/comments")
```

Access statistics from the decorated function:

```python
# Get rate limit statistics directly from the decorated function
stats = fetch_user.get_stats()
print(f"Total requests: {stats.total_requests}")
```

### Client-based Approach

You can also use the explicit client approach:

```python
from rate_limiter import RateLimitedClient

# Create a client with default settings (100 req/min)
client = RateLimitedClient()

# Use the execute method - handles all rate limiting automatically
response = await client.execute(api_call)

# Can also call methods with arguments
response = await client.execute(api_client.get, "/users", headers={"Accept": "application/json"})
```

### Context Manager Usage

For more control, you can use the context manager:

```python
from rate_limiter import RateLimitedClient

client = RateLimitedClient()

# Use with context manager
async with client:
    response = await api_call()
```

### execute() vs Context Manager

The `execute()` method and context manager approach (`async with`) provide different levels of functionality:

```python
# execute() approach - RECOMMENDED
response = await client.execute(api_call)

# Context manager approach
async with client:
    response = await api_call()
```

**Key differences:**

1. **Error handling:**
   - `execute()`: Provides robust error handling with automatic retries for rate limit errors (up to 3 retries by default)
   - Context manager: Only updates the rate limiter when errors occur but doesn't retry automatically

2. **Rate limit detection:**
   - `execute()`: Automatically detects rate limit errors through status codes (429) and error messages
   - Context manager: Captures any exception and updates the rate limiter, but doesn't distinguish rate limit errors

3. **Ease of use:**
   - `execute()`: Handles the entire request flow in one method call
   - Context manager: Requires additional error handling code from the user

For most use cases, the `execute()` method is recommended as it provides more comprehensive rate limit handling.

### Data Models

The rate limiter uses Pydantic models for both configuration and statistics, providing better validation, documentation, and developer experience.

#### Configuration

```python
from rate_limiter import RateLimitConfig, RateLimitStrategy

# Create a configuration with validation
config = RateLimitConfig(
    max_requests=100,
    time_window=60,
    strategy=RateLimitStrategy.ADAPTIVE,
    burst_size=150  # Only used with BURST strategy
)

# Access with proper type hints
print(f"Strategy: {config.strategy}")
print(f"Requests per minute: {config.max_requests / (config.time_window/60)}")
```

The `RateLimitConfig` model validates inputs (e.g., ensuring positive values for requests and time windows) and provides descriptive field documentation visible in modern IDEs.

#### Statistics

As shown in the Monitoring section, the `get_stats()` method returns a `RateLimiterStats` Pydantic model that provides type hints, validation, and descriptive field documentation.

### Project-wide Configuration

```python
from rate_limiter import configure

# Set project defaults
configure(
    max_requests=200,    # 200 requests
    time_window=60       # per minute
)
```

### Per-call Overrides

```python
from rate_limiter import RateLimitedClient

client = RateLimitedClient()

# With execute
response = await client.with_options(max_requests=50).execute(api_call)

# Or with context manager
async with client.with_options(max_requests=50):
    response = await api_call()
```

### Adaptive Rate Limiting

The ADAPTIVE strategy can automatically adjust based on API response headers:

```python
from rate_limiter import adaptive_rate_limited

# Use the adaptive decorator
@adaptive_rate_limited()
async def fetch_data():
    return await api_client.get("/data")
```

The rate limiter will automatically detect and adapt to:
- `Retry-After` headers
- `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers
- Various vendor-specific rate limit headers (GitHub, Twitter, AWS, etc.)
- Rate limit information in error messages

### Custom Header Extraction

You can provide a custom function to extract headers from responses:

```python
def extract_my_headers(response):
    """Extract headers from a custom response object"""
    headers = {}
    if hasattr(response, 'custom_headers'):
        headers = response.custom_headers
    return headers

# Use with decorator
@rate_limited(
    strategy=RateLimitStrategy.ADAPTIVE,
    extract_headers_callback=extract_my_headers
)
async def fetch_data():
    return await api_client.get("/data")
```

### Monitoring

```python
# Get current statistics from a decorated function
stats = fetch_data.get_stats()
print(f"Total requests: {stats.total_requests}")
print(f"Current rate: {stats.current_rate} requests/minute")
print(f"Total wait time: {stats.total_wait_time} seconds")
print(f"Rate limit hits: {stats.rate_limit_hits}")

# Check dynamic adaptations (if any)
if stats.dynamic_adjustments:
    print(f"Last update: {stats.last_dynamic_update}")
    for key, value in stats.dynamic_adjustments.items():
        print(f"  {key}: {value}")
```

The `get_stats()` method returns a `RateLimiterStats` Pydantic model with the following fields:

```python
from rate_limiter import RateLimiterStats

# Required fields (always present)
stats.total_requests      # Total number of requests processed
stats.total_wait_time     # Total time spent waiting in seconds
stats.max_wait_time       # Maximum wait time encountered in seconds
stats.current_rate        # Current request rate in requests per minute
stats.current_queue_size  # Current number of requests in the tracking queue
stats.rate_limit_hits     # Number of rate limit errors encountered

# Optional fields (only present under certain conditions)
stats.last_dynamic_update       # Timestamp of last dynamic adaptation
stats.dynamic_adjustments       # Dictionary of dynamic rate limit adjustments
stats.last_rate_limit_hit       # Timestamp of last rate limit hit
stats.time_since_last_rate_limit  # Seconds since last rate limit hit
stats.rate_limit_expiry_in      # Seconds until rate limit tracking expires
```

Using the Pydantic model provides better type hints, validation, and IntelliSense support in modern IDEs.

### Utility Functions

#### Detecting Rate Limit Errors

You can identify rate limit errors in your own error handling code:

```python
from rate_limiter import is_rate_limit_error

try:
    response = await api_client.get("/endpoint")
except Exception as e:
    if is_rate_limit_error(e):
        print("Hit a rate limit, backing off...")
        await asyncio.sleep(30)
        # Retry logic
    else:
        # Handle other types of errors
        raise
```

The `is_rate_limit_error` function detects rate limit errors by checking:
- HTTP 429 status codes
- Common rate limit phrases in error messages
- Standard response patterns across different APIs

This utility can be helpful when building custom rate limit handling or for diagnostic purposes.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details. 
