from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import CurrentStaff, get_current_staff
from app.db.session import get_db
from app.rbac.access import AccessContext, require_permission
from app.schemas.workspace import TaskCreate, TaskPatch, TaskRead
from app.services.tasks import TaskService

router = APIRouter(prefix='/tasks', tags=['Tasks'])

def svc(db: AsyncSession): return TaskService(db)

@router.get('', response_model=list[TaskRead])
async def list_tasks(db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff), access: AccessContext = Depends(require_permission("task", "view"))):
    return await svc(db).repo.list_for_staff(user.id, user.organization_id, user.company_id)

@router.post('', response_model=TaskRead, status_code=201)
async def create_task(payload: TaskCreate, db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff), access: AccessContext = Depends(require_permission("task", "create", write=True))):
    row = await svc(db).create(user.id, user.organization_id, payload); await db.commit(); return row

@router.get('/{task_id}', response_model=TaskRead)
async def get_task(task_id: UUID, db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff), access: AccessContext = Depends(require_permission("task", "view"))):
    from fastapi import HTTPException
    row = await svc(db).repo.get_for_staff(task_id, user.id, user.organization_id)
    if not row: raise HTTPException(404, 'Task not found')
    return row

@router.patch('/{task_id}', response_model=TaskRead)
async def patch_task(task_id: UUID, payload: TaskPatch, db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff), access: AccessContext = Depends(require_permission("task", "update", write=True))):
    row = await svc(db).update(task_id, user.id, user.organization_id, payload); await db.commit(); return row

@router.post('/{task_id}/{action}', response_model=TaskRead)
async def transition_task(task_id: UUID, action: str, db: AsyncSession = Depends(get_db), user: CurrentStaff = Depends(get_current_staff), access: AccessContext = Depends(require_permission("task", "update", write=True))):
    actions = {'accept':'accepted','start':'in_progress','wait':'waiting','complete':'completed','verify':'verified','close':'closed','reopen':'reopened','cancel':'cancelled'}
    from fastapi import HTTPException
    if action not in actions: raise HTTPException(404, 'Unsupported task action')
    required = {'complete':'complete','verify':'verify','close':'close'}.get(action)
    if required and not access.can('task', required): raise HTTPException(403, f'Missing permission: task:{required}')
    row = await svc(db).transition(task_id, user.id, user.organization_id, actions[action]); await db.commit(); return row
