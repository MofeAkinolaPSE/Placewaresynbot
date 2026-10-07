from fastapi import APIRouter, Depends
from app.models.event import OperationalEvent
from app.schemas.operational import OperationalEventIn, RuleCreate

router = APIRouter(prefix='/operational', tags=['Operational Events'])

# Host application supplies these dependencies.
def get_operational_service():
    raise NotImplementedError('Bind Synbot OperationalTaskService in the application container')

def get_rule_repo():
    raise NotImplementedError('Bind Synbot operational rule repository in the application container')

@router.post('/events')
async def ingest_event(payload: OperationalEventIn, service=Depends(get_operational_service)):
    event = OperationalEvent(
        event_id=payload.event_id, event_type=payload.event_type,
        entity_type=payload.entity_type, entity_id=payload.entity_id,
        company_id=payload.company_id, facility_id=payload.facility_id,
        department_id=payload.department_id, team_id=payload.team_id,
        actor_staff_id=payload.actor_staff_id,
        occurred_at=payload.occurred_at or OperationalEvent.__dataclass_fields__['occurred_at'].default_factory(),
        payload=payload.payload,
    )
    return await service.handle_event(event)

@router.post('/rules')
async def create_rule(payload: RuleCreate, repo=Depends(get_rule_repo)):
    return await repo.create(payload.model_dump())

@router.get('/rules')
async def list_rules(company_id: int, repo=Depends(get_rule_repo)):
    return await repo.list_for_company(company_id)
