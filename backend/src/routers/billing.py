from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from src.middleware import verify_jwt
from src.workflow.credit_risk import is_customer_flagged, apply_credit_action

router = APIRouter(prefix="/billing", tags=["billing"])


class InvoiceCreate(BaseModel):
    customer_id: str
    amount: float


@router.post("/create_invoice")
async def api_create_invoice(payload: InvoiceCreate, request: Request, user=Depends(lambda r: verify_jwt(r))):
    # Check credit flags
    if is_customer_flagged(payload.customer_id):
        # record attempted invoice creation
        apply_credit_action(payload.customer_id, "invoice_blocked", {"amount": payload.amount})
        raise HTTPException(status_code=403, detail="Customer is credit-blocked")
    # Here we would call existing order/invoice creation pipeline; for now return placeholder
    return {"ok": True, "invoice_id": "inv_placeholder", "amount": payload.amount}
