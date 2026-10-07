from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import CurrentStaff, get_current_staff
from app.db.session import get_db
from app.schemas.workspace import WorkspaceRead
from app.services.workspace import WorkspaceService

router = APIRouter(prefix='/workspace', tags=['Workspace'])

@router.get('', response_model=WorkspaceRead)
async def workspace(db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff)):
    result = await WorkspaceService(db).get(user.id, user.organization_id, user.company_id)
    if not result: raise HTTPException(404, 'Staff profile not found')
    return result
