from fastapi import APIRouter, Request
from src.eos.service import router as eos_service_router

router = APIRouter()

# Mount eos service under /eos
router.include_router(eos_service_router, prefix="/eos")
