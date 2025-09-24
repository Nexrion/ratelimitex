import pytest

from ratelimitex.models import RateLimitConfig, RateLimitStrategy


def test_rate_limit_config_defaults():
    """Test that RateLimitConfig has proper defaults."""
    config = RateLimitConfig()
    assert config.max_requests > 0
    assert config.time_window > 0
    assert config.strategy == RateLimitStrategy.STRICT


def test_rate_limit_config_custom_values():
    """Test that RateLimitConfig can be initialized with custom values."""
    config = RateLimitConfig(max_requests=10, time_window=60, strategy=RateLimitStrategy.ADAPTIVE)
    assert config.max_requests == 10
    assert config.time_window == 60
    assert config.strategy == RateLimitStrategy.ADAPTIVE


def test_rate_limit_config_validation():
    """Test that RateLimitConfig validates input values."""
    with pytest.raises(ValueError):
        RateLimitConfig(max_requests=0)

    with pytest.raises(ValueError):
        RateLimitConfig(time_window=0)

    with pytest.raises(ValueError):
        RateLimitConfig(max_requests=-1)

    with pytest.raises(ValueError):
        RateLimitConfig(time_window=-1)


def test_rate_limit_config_equality():
    """Test that RateLimitConfig instances can be compared."""
    config1 = RateLimitConfig(max_requests=10, time_window=60)
    config2 = RateLimitConfig(max_requests=10, time_window=60)
    config3 = RateLimitConfig(max_requests=20, time_window=60)

    assert config1 == config2
    assert config1 != config3
