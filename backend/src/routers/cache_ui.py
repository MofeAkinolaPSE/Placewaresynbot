from fastapi import APIRouter, Depends, HTTPException
from typing import Any
from src.utils.ttl_cache import SimpleTTLCache
from src.middleware import verify_jwt

# Minimal in-memory shared cache instance used by agents at runtime.
_shared_cache = SimpleTTLCache()

router = APIRouter(prefix="/cache", tags=["cache"])


def get_shared_cache() -> SimpleTTLCache:
    return _shared_cache


@router.get("/get/{key}")
async def api_cache_get(key: str, _u=Depends(lambda r: verify_jwt(r))):
    v = _shared_cache.get(key)
    return {"key": key, "value": v}


@router.get("/ttl/{key}")
async def api_cache_ttl(key: str, _u=Depends(lambda r: verify_jwt(r))):
    ttl = _shared_cache.ttl(key)
    return {"key": key, "ttl_seconds": ttl}


@router.post("/clear")
async def api_cache_clear(_u=Depends(lambda r: verify_jwt(r, required_role="admin"))):
    _shared_cache.clear()
    return {"ok": True}
