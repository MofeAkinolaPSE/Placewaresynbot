import logging
from fastapi import APIRouter, Depends, HTTPException
from typing import Any
from src.utils.ttl_cache import SimpleTTLCache
from src.middleware import verify_jwt, require_role

logger = logging.getLogger(__name__)

# Shared cache instance used by agents/tools at runtime. Backed by Redis when
# reachable (shared across processes, system-wide -- every caller reaches
# this through get_shared_cache() below); falls back to the in-memory
# SimpleTTLCache if Redis isn't available at startup (e.g. local dev without
# the redis container running) so the app still works, just without a
# cross-process cache.
try:
    from src.utils.redis_cache import RedisTTLCache
    _shared_cache = RedisTTLCache()
    logger.info("Shared cache backend: Redis")
except Exception as exc:
    logger.warning("Redis unavailable at startup (%s); falling back to in-memory cache", exc)
    _shared_cache = SimpleTTLCache()

router = APIRouter(prefix="/cache", tags=["cache"])


def get_shared_cache() -> SimpleTTLCache:
    return _shared_cache


@router.get("/get/{key}")
async def api_cache_get(key: str, _u=Depends(verify_jwt)):
    v = _shared_cache.get(key)
    return {"key": key, "value": v}


@router.get("/ttl/{key}")
async def api_cache_ttl(key: str, _u=Depends(verify_jwt)):
    ttl = _shared_cache.ttl(key)
    return {"key": key, "ttl_seconds": ttl}


@router.post("/clear")
async def api_cache_clear(_u=Depends(require_role("admin"))):
    _shared_cache.clear()
    return {"ok": True}
