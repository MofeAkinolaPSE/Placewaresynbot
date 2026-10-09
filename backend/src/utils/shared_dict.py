"""A dict shared by every uvicorn worker (Redis), for short-lived state that one request
creates and a later request reads - e.g. a chat draft waiting for "yes, send it", or an upload
token. With several workers the second request often lands on a different worker, so a plain
module-level dict would lose it. Falls back to a per-process dict if Redis is unreachable.

Supports what the callers use: d.get(k), d[k] = v, del d[k], k in d.
"""
from __future__ import annotations

import logging
import pickle
from typing import Any, Dict

import redis

from src.constants import REDIS_URL

logger = logging.getLogger(__name__)


class SharedDict:
    def __init__(self, name: str, ttl_seconds: int) -> None:
        self._prefix = f"pw:dict:{name}:"
        self._ttl = ttl_seconds
        self._local: Dict[str, Any] = {}
        try:
            self._r = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=3)
        except Exception:  # bad URL - stay local
            self._r = None

    def _k(self, key: Any) -> str:
        return self._prefix + str(key)

    def get(self, key: Any, default: Any = None) -> Any:
        if self._r is not None:
            try:
                raw = self._r.get(self._k(key))
                return pickle.loads(raw) if raw is not None else default
            except Exception as exc:
                logger.warning("SharedDict %s: Redis get failed (%s); using local", self._prefix, exc)
        return self._local.get(key, default)

    def __setitem__(self, key: Any, value: Any) -> None:
        if self._r is not None:
            try:
                self._r.set(self._k(key), pickle.dumps(value), ex=self._ttl)
                return
            except Exception as exc:
                logger.warning("SharedDict %s: Redis set failed (%s); using local", self._prefix, exc)
        self._local[key] = value

    def __delitem__(self, key: Any) -> None:
        self._local.pop(key, None)
        if self._r is not None:
            try:
                self._r.delete(self._k(key))
            except Exception as exc:
                logger.warning("SharedDict %s: Redis delete failed (%s)", self._prefix, exc)

    def __contains__(self, key: Any) -> bool:
        return self.get(key) is not None


__all__ = ["SharedDict"]
