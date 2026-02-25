from __future__ import annotations

import threading
import time
from functools import wraps
from typing import Any, Callable, Dict, Hashable, Iterable, Tuple


class _TTLCache:
    """Simple in-process TTL cache for computed aggregates.

    This is intentionally lightweight and process-local. For multiple workers
    each process keeps its own cache, which is acceptable for our dashboard
    use-cases.
    """

    def __init__(self) -> None:
        self._store: Dict[Hashable, Tuple[float, Any]] = {}
        self._lock = threading.RLock()

    def get(self, key: Hashable) -> Any | None:
        now = time.time()
        with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            expires_at, value = item
            if expires_at < now:
                # Expired
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: Hashable, value: Any, ttl_seconds: int) -> None:
        expires_at = time.time() + ttl_seconds
        with self._lock:
            self._store[key] = (expires_at, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

_global_cache = _TTLCache()


def _make_key(
    func_name: str,
    args: Tuple[Any, ...],
    kwargs: Dict[str, Any],
    ignore_kwargs: Iterable[str],
) -> Hashable:
    """Build a hashable cache key.

    We deliberately ignore non-deterministic kwargs (like `client`).
    """
    filtered_kwargs = {k: v for k, v in kwargs.items() if k not in set(ignore_kwargs)}
    # Rely on callers to only pass hashable args/kwargs that matter for caching.
    return (
        func_name,
        args,
        tuple(sorted(filtered_kwargs.items(), key=lambda item: item[0])),
    )


def ttl_cache(ttl_seconds: int, ignore_kwargs: Iterable[str] | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to cache function results for a fixed TTL.

    Designed for pure/aggregate read operations (no side-effects).
    """

    if ignore_kwargs is None:
        ignore_kwargs = []

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _make_key(func.__name__, args, kwargs, ignore_kwargs)
            cached = _global_cache.get(key)
            if cached is not None:
                return cached
            value = func(*args, **kwargs)
            _global_cache.set(key, value, ttl_seconds)
            return value

        return wrapper

    return decorator
