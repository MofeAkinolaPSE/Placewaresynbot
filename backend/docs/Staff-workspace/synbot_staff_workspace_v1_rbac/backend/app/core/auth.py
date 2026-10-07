from dataclasses import dataclass
from uuid import UUID
from fastapi import Depends, Header, HTTPException, status

@dataclass(frozen=True)
class CurrentStaff:
    id: UUID
    organization_id: UUID
    company_id: UUID | None = None

# Replace this resolver with Synbot's existing JWT/auth dependency.
# The development header fallback is deliberately explicit and should not be enabled in production.
async def get_current_staff(
    x_staff_id: str | None = Header(default=None),
    x_organization_id: str | None = Header(default=None),
    x_company_id: str | None = Header(default=None),
) -> CurrentStaff:
    if not x_staff_id or not x_organization_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Authentication required')
    try:
        return CurrentStaff(UUID(x_staff_id), UUID(x_organization_id), UUID(x_company_id) if x_company_id else None)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail='Invalid identity headers') from exc
