from __future__ import annotations
import threading
import time
from typing import Any, Optional


def _bk(key):
    """Each branch (Lagos / Abuja) keeps its own cached values - see src/branch.py."""
    from src.branch import cache_key
    return cache_key(key)


class SimpleTTLCache:
    """A tiny thread-safe TTL cache suitable for agent result caching.

    Usage:
        cache = SimpleTTLCache()
        cache.set('k', value, ttl=60)
        v = cache.get('k')
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        key = _bk(key)
        expiry = float('inf') if ttl is None else time.time() + float(ttl)
        with self._lock:
            self._store[key] = (expiry, value)

    def get(self, key: str) -> Optional[Any]:
        key = _bk(key)
        with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            expiry, value = item
            if expiry < time.time():
                # expired
                del self._store[key]
                return None
            return value

    def delete(self, key: str) -> None:
        key = _bk(key)
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def ttl(self, key: str) -> Optional[float]:
        key = _bk(key)
        with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            expiry, _ = item
            remaining = expiry - time.time()
            return None if remaining == float('inf') else max(0.0, remaining)


__all__ = ["SimpleTTLCache"]
