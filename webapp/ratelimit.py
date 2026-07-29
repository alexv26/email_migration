from redis import Redis


def check_rate_limit(redis: Redis, key: str, limit: int, window_seconds: int = 3600) -> bool:
    """Fixed-window limiter. Returns True (and counts the call) if under the
    limit, False if the limit has already been reached for this window."""
    full_key = f"ratelimit:{key}"
    count = redis.incr(full_key)
    if count == 1:
        redis.expire(full_key, window_seconds)
    return count <= limit
