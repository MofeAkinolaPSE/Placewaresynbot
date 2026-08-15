from fastapi import APIRouter, Depends
from src.middleware import verify_jwt
from src.services.presence_service import record_heartbeat, get_online_users

router = APIRouter(prefix="/presence", tags=["presence"])


@router.post("/heartbeat")
async def heartbeat(user: dict = Depends(verify_jwt)):
    """Called every 30s by PresenceHeartbeat.tsx for the whole duration of
    an authenticated session, regardless of which page is active."""
    record_heartbeat(user.get("sub"), user.get("roles") or [])
    return {"status": "ok"}


@router.get("/online")
async def online(_u: dict = Depends(verify_jwt)):
    """Global roster, deliberately not department-scoped -- any
    authenticated user can see who else currently has the app open."""
    users = get_online_users()
    return {"users": users, "count": len(users)}
