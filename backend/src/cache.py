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
        self._tag_index: Dict[str, set[Hashable]] = {}
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
                self._remove_key_from_tags(key)
                return None
            return value

    def set(self, key: Hashable, value: Any, ttl_seconds: int, tags: Iterable[str] | None = None) -> None:
        expires_at = time.time() + ttl_seconds
        with self._lock:
            self._store[key] = (expires_at, value)
            if tags:
                for tag in tags:
                    normalized = (tag or "").strip()
                    if not normalized:
                        continue
                    self._tag_index.setdefault(normalized, set()).add(key)

    def invalidate_tags(self, tags: Iterable[str]) -> int:
        removed = 0
        with self._lock:
            for tag in tags:
                normalized = (tag or "").strip()
                if not normalized:
                    continue
                keys = list(self._tag_index.get(normalized, set()))
                for key in keys:
                    if key in self._store:
                        self._store.pop(key, None)
                        removed += 1
                    self._remove_key_from_tags(key)
                self._tag_index.pop(normalized, None)
        return removed

    def _remove_key_from_tags(self, key: Hashable) -> None:
        empty_tags: list[str] = []
        for tag, keys in self._tag_index.items():
            if key in keys:
                keys.discard(key)
            if not keys:
                empty_tags.append(tag)
        for tag in empty_tags:
            self._tag_index.pop(tag, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._tag_index.clear()

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


def ttl_cache(
    ttl_seconds: int,
    ignore_kwargs: Iterable[str] | None = None,
    tags: Iterable[str] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
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
            _global_cache.set(key, value, ttl_seconds, tags=tags)
            return value

        return wrapper

    return decorator


def invalidate_cache_tags(*tags: str) -> int:
    return _global_cache.invalidate_tags(tags)


def clear_cache() -> None:
    _global_cache.clear()
