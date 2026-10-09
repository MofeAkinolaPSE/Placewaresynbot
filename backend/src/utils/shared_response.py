"""Cross-worker response cache for expensive reads (Redis), with single-flight.

    shared_response("fin:dashboard:<entity>:<as_of>", 60, build)

* Shared by every uvicorn worker, so a report computed once is served to all 30-50 laptops.
* Single-flight: when the key is missing, one caller builds it while the others wait for the
  result instead of all running the same heavy query at once (a "stampede").
* Keys include the data version, which bump_data_version() advances after every successful write
  request (see DataVersionMiddleware). Any save anywhere makes every cached report stale at once,
  so nobody sees old figures after an edit; the TTL only bounds memory.
* If Redis is down, everything still works: values are built fresh (with a small per-process
  cache) - never slower than having no cache, never an error.

Values are pickled: they are written and read only by this backend (same trust boundary as
src/utils/redis_cache.py).
"""
from __future__ import annotations

import logging
import pickle
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

import redis

from src.constants import REDIS_URL

logger = logging.getLogger(__name__)

_PREFIX = "pw:resp:"
_VERSION_KEY = "pw:data_version"
_LOCK_SECONDS = 60          # a builder that dies frees the key after this
_WAIT_SECONDS = 30.0        # how long a waiter waits for another worker's build
_COOLDOWN = 5.0             # after a Redis error, skip Redis for this long

_client: Optional[redis.Redis] = None
_client_lock = threading.Lock()
_down_until = 0.0
_local: Dict[str, Tuple[float, Any]] = {}
_local_lock = threading.Lock()


def _redis() -> Optional[redis.Redis]:
    global _client
    if time.time() < _down_until:
        return None
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=3)
    return _client


def _trip(exc: Exception, op: str) -> None:
    global _down_until
    _down_until = time.time() + _COOLDOWN
    logger.warning("shared_response: Redis %s failed (%s); serving uncached for %.0fs", op, exc, _COOLDOWN)


def data_version() -> str:
    r = _redis()
    if r is None:
        return "local"
    try:
        v = r.get(_VERSION_KEY)
        return v.decode() if v else "0"
    except Exception as exc:
        _trip(exc, "version")
        return "local"


def bump_data_version() -> None:
    """Call after any write that could change what a cached read returns."""
    with _local_lock:
        _local.clear()
    r = _redis()
    if r is None:
        return
    try:
        r.incr(_VERSION_KEY)
    except Exception as exc:
        _trip(exc, "bump")


def _local_get(key: str) -> Any:
    with _local_lock:
        item = _local.get(key)
        if item and item[0] > time.time():
            return item[1]
    return None


def _local_set(key: str, value: Any, ttl: int) -> None:
    with _local_lock:
        if len(_local) > 500:
            _local.clear()
        _local[key] = (time.time() + ttl, value)


def shared_response(key: str, ttl_seconds: int, build: Callable[[], Any]) -> Any:
    """Return the cached value for key, building it (once across all workers) when missing."""
    full = f"{_PREFIX}{data_version()}:{key}"
    r = _redis()
    if r is None:
        hit = _local_get(full)
        if hit is not None:
            return hit
        value = build()
        _local_set(full, value, ttl_seconds)
        return value
    try:
        raw = r.get(full)
        if raw is not None:
            return pickle.loads(raw)
        lock = full + ":building"
        if not r.set(lock, b"1", nx=True, ex=_LOCK_SECONDS):
            # Another worker is building it: wait for its result rather than repeat the work.
            deadline = time.monotonic() + _WAIT_SECONDS
            while time.monotonic() < deadline:
                time.sleep(0.05)
                raw = r.get(full)
                if raw is not None:
                    return pickle.loads(raw)
                if not r.exists(lock):
                    break
    except Exception as exc:
        _trip(exc, "get")
        return build()
    try:
        value = build()
    except Exception:
        try:
            r.delete(full + ":building")
        except Exception:
            pass
        raise
    try:
        pipe = r.pipeline()
        pipe.set(full, pickle.dumps(value), ex=ttl_seconds)
        pipe.delete(full + ":building")
        pipe.execute()
    except Exception as exc:
        _trip(exc, "set")
    return value


__all__ = ["shared_response", "bump_data_version", "data_version"]
