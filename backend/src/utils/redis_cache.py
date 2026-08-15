from __future__ import annotations
import logging
import pickle
import time
from typing import Any, Optional

import redis

from src.constants import REDIS_URL

logger = logging.getLogger(__name__)

_KEY_PREFIX = "pw:cache:"

# After a failed Redis call, stop attempting new ones for this long. Without
# this, an outage (e.g. the container stopped, DNS lookup for the service
# name failing) makes every single cache call pay a fresh, slow connection/
# DNS-resolution attempt -- observed to make requests *slower* than having
# no cache at all, since callers hit the cache many times per request.
_CIRCUIT_COOLDOWN_SECONDS = 5.0


class RedisTTLCache:
    """Drop-in replacement for SimpleTTLCache (src/utils/ttl_cache.py),
    backed by Redis so the cache is shared across processes/workers instead
    of living in one process's memory.

    Same public interface (get/set/delete/clear/ttl) so every existing
    caller that reaches the cache through get_shared_cache() works
    unchanged. Values are pickled -- callers store arbitrary Python objects
    (dataclass Insight instances, dicts with datetimes, etc.), and this data
    never leaves the backend's own trust boundary (written and read only by
    this app), so pickle is safe here.

    Every Redis call is wrapped in try/except: on any connection error,
    get() returns None (a clean cache miss -- the caller just computes
    fresh, identical to today's behavior) and set()/delete() no-op with a
    warning. A simple circuit breaker (see _CIRCUIT_COOLDOWN_SECONDS) means
    a Redis outage costs at most one slow attempt, then short-circuits to
    "unavailable" instantly for a few seconds before trying again -- Redis
    being unreachable can only make things as slow as having no cache,
    never slower, and never breaks a request.
    """

    def __init__(self, url: str | None = None) -> None:
        self._client = redis.Redis.from_url(url or REDIS_URL, socket_connect_timeout=3, socket_timeout=3)
        self._client.ping()  # raises if Redis isn't reachable -- caller decides the fallback
        self._circuit_open_until = 0.0

    @staticmethod
    def _k(key: str) -> str:
        return f"{_KEY_PREFIX}{key}"

    def _circuit_available(self) -> bool:
        return time.time() >= self._circuit_open_until

    def _trip_circuit(self, exc: Exception, op: str, key: str = "") -> None:
        self._circuit_open_until = time.time() + _CIRCUIT_COOLDOWN_SECONDS
        logger.warning("RedisTTLCache.%s failed for key=%s (circuit open for %.0fs): %s", op, key, _CIRCUIT_COOLDOWN_SECONDS, exc)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        if not self._circuit_available():
            return
        try:
            payload = pickle.dumps(value)
            if ttl is None:
                self._client.set(self._k(key), payload)
            else:
                self._client.set(self._k(key), payload, ex=int(ttl))
        except Exception as exc:
            self._trip_circuit(exc, "set", key)

    def get(self, key: str) -> Optional[Any]:
        if not self._circuit_available():
            return None
        try:
            raw = self._client.get(self._k(key))
            if raw is None:
                return None
            return pickle.loads(raw)
        except Exception as exc:
            self._trip_circuit(exc, "get", key)
            return None

    def delete(self, key: str) -> None:
        if not self._circuit_available():
            return
        try:
            self._client.delete(self._k(key))
        except Exception as exc:
            self._trip_circuit(exc, "delete", key)

    def clear(self) -> None:
        if not self._circuit_available():
            return
        try:
            self._client.flushdb()
        except Exception as exc:
            self._trip_circuit(exc, "clear")

    def ttl(self, key: str) -> Optional[float]:
        if not self._circuit_available():
            return None
        try:
            remaining = self._client.ttl(self._k(key))
            # -2 = key doesn't exist, -1 = exists but no expiry -- both map
            # to None to match SimpleTTLCache's "no active TTL" contract.
            if remaining is None or remaining < 0:
                return None
            return float(remaining)
        except Exception as exc:
            self._trip_circuit(exc, "ttl", key)
            return None


__all__ = ["RedisTTLCache"]
