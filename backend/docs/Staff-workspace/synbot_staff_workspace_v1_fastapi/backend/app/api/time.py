from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import CurrentStaff, get_current_staff
from app.db.session import get_db
from app.schemas.workspace import TimeRead
from app.services.time import TimeService

router = APIRouter(prefix='/time', tags=['Time'])

@router.get('/today', response_model=TimeRead | None)
async def today(db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    return await TimeService(db).repo.active(user.id)

@router.post('/start', response_model=TimeRead)
async def start(db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    row = await TimeService(db).start(user.id, user.company_id); await db.commit(); return row

@router.post('/pause', response_model=TimeRead)
async def pause(db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    row = await TimeService(db).pause(user.id); await db.commit(); return row

@router.post('/resume', response_model=TimeRead)
async def resume(db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    row = await TimeService(db).resume(user.id); await db.commit(); return row

@router.post('/end', response_model=TimeRead)
async def end(db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    row = await TimeService(db).end(user.id); await db.commit(); return row
