from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

@dataclass(frozen=True)
class OperationalEvent:
    event_id: str
    event_type: str
    entity_type: str
    entity_id: str
    company_id: int
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    facility_id: int | None = None
    department_id: int | None = None
    team_id: int | None = None
    actor_staff_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
