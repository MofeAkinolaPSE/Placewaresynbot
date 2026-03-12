from fastapi import APIRouter, HTTPException
import src.db as db

router = APIRouter(prefix='/crm', tags=['crm'])


@router.get('/customers/{customer_id}/360')
def customer_360(customer_id: int):
    try:
        res = db.db.table('customer_360').select('*').eq('customer_id', customer_id).limit(1).execute()
        rows = res.data or []
        if not rows:
            raise HTTPException(status_code=404, detail='Customer 360 not found')
        return rows[0]
    except Exception:
        raise HTTPException(status_code=500, detail='Failed reading customer 360')
