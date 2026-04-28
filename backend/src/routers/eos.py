from fastapi import APIRouter, Request
from src.eos.service import router as eos_service_router

router = APIRouter()

# Mount eos service — prefix is already defined in service.py (prefix="/eos")
# Do NOT add another prefix here or routes will become /eos/eos/...
router.include_router(eos_service_router)
