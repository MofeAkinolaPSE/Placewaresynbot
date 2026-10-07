from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import CurrentStaff, get_current_staff
from app.db.session import get_db
from app.schemas.collaboration import RequestCreate, RequestRead, RequestMessageCreate, RequestMessageRead, ActivityRead
from app.services.collaboration import CollaborationService

router = APIRouter(prefix='/requests', tags=['Collaboration'])

def svc(db): return CollaborationService(db)

@router.get('', response_model=list[RequestRead])
async def list_requests(db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    return await svc(db).repo.list_for_staff(user.id, user.organization_id, user.company_id)

@router.post('', response_model=RequestRead, status_code=201)
async def create_request(payload: RequestCreate, db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    row = await svc(db).create(user.id, user.organization_id, user.company_id, payload); await db.commit(); return row

@router.get('/{request_id}', response_model=RequestRead)
async def get_request(request_id: UUID, db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    from fastapi import HTTPException
    row = await svc(db).repo.get(request_id, user.id, user.organization_id)
    if not row: raise HTTPException(404, 'Request not found')
    return row

@router.post('/{request_id}/{action}', response_model=RequestRead)
async def transition(request_id: UUID, action: str, db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    mapping = {'acknowledge':'acknowledged','start':'in_progress','respond':'responded','close':'closed','cancel':'cancelled','reopen':'in_progress'}
    from fastapi import HTTPException
    if action not in mapping: raise HTTPException(404, 'Unsupported request action')
    row = await svc(db).transition(request_id, user.id, user.organization_id, mapping[action]); await db.commit(); return row

@router.get('/{request_id}/messages', response_model=list[RequestMessageRead])
async def messages(request_id: UUID, db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    if not await svc(db).repo.get(request_id, user.id, user.organization_id):
        from fastapi import HTTPException; raise HTTPException(404, 'Request not found')
    return await svc(db).repo.messages(request_id)

@router.post('/{request_id}/messages', response_model=RequestMessageRead, status_code=201)
async def add_message(request_id: UUID, payload: RequestMessageCreate, db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    msg = await svc(db).add_message(request_id, user.id, user.organization_id, payload); await db.commit(); return msg

@router.get('/{request_id}/activity', response_model=list[ActivityRead])
async def activity(request_id: UUID, db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    if not await svc(db).repo.get(request_id, user.id, user.organization_id):
        from fastapi import HTTPException; raise HTTPException(404, 'Request not found')
    return await svc(db).repo.activity(request_id)
