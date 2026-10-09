from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import List
from src.middleware import verify_jwt, require_role
from src.workflow.credit_risk import is_customer_flagged, apply_credit_action
from src.workflow.batch_locking import enforce_no_locked_batches

router = APIRouter(prefix="/billing", tags=["billing"])


class InvoiceCreate(BaseModel):
    customer_id: str
    amount: float
    batch_ids: List[str] = []


@router.post("/create_invoice")
def api_create_invoice(payload: InvoiceCreate, request: Request, user=Depends(verify_jwt)):
    # Compliance lock enforcement
    enforce_no_locked_batches(payload.batch_ids)

    # Check credit flags
    if is_customer_flagged(payload.customer_id):
        # record attempted invoice creation
        apply_credit_action(payload.customer_id, "invoice_blocked", {"amount": payload.amount})
        raise HTTPException(status_code=403, detail="Customer is credit-blocked")
    # Here we would call existing order/invoice creation pipeline; for now return placeholder
    return {"ok": True, "invoice_id": "inv_placeholder", "amount": payload.amount}
