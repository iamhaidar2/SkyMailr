"""Simple cache-backed rate limits for public portal endpoints."""

from __future__ import annotations

from django.core.cache import cache


def allow_request(key: str, *, limit: int, window_seconds: int) -> bool:
    """Sliding-style counter: increment per key; block when count exceeds limit."""
    n = cache.get(key, 0)
    if n >= limit:
        return False
    cache.set(key, n + 1, window_seconds)
    return True
