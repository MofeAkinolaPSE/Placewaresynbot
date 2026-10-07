"""Business errors with stable codes (Financial API spec §60-61).

Raised as FinError anywhere in the engine; the API layer turns them into
HTTP errors whose `detail` carries {code, message, details} so the existing
frontend client (which reads `detail.message`) shows the business reason.
Database integrity triggers raise messages prefixed `FIN_<CODE>:`; those are
translated here too, so a constraint caught only by Postgres still surfaces
as a proper business error rather than a 500.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

_STATUS = {
    "PERMISSION_DENIED": 403,
    "RESOURCE_NOT_FOUND": 404,
    "VALIDATION_FAILED": 422,
    "DUPLICATE_RESOURCE": 409,
    "DUPLICATE_INVOICE": 409,
    "DUPLICATE_REFERENCE": 409,
    "PERIOD_CLOSED": 409,
    "PERIOD_NOT_FOUND": 409,
    "PERIOD_MISMATCH": 409,
    "ACCOUNT_INACTIVE": 409,
    "ACCOUNT_NOT_POSTABLE": 409,
    "CONTROL_ACCOUNT": 403,
    "UNBALANCED_JOURNAL": 422,
    "APPROVAL_REQUIRED": 409,
    "CREDIT_LIMIT_EXCEEDED": 409,
    "INSUFFICIENT_STOCK": 409,
    "INVALID_BATCH": 422,
    "TRANSACTION_ALREADY_POSTED": 409,
    "INVALID_STATE_TRANSITION": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "POSTED_IMMUTABLE": 409,
    "AUDIT_IMMUTABLE": 409,
    "OVER_ALLOCATION": 422,
    "MAPPING_MISSING": 409,
    "CLOSE_BLOCKED": 409,
    "RECONCILIATION_EXCEPTION": 422,
}


class FinError(Exception):
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None,
                 status: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status = status or _STATUS.get(code, 400)

    def to_detail(self, request_id: Optional[str] = None) -> Dict[str, Any]:
        d = {"code": self.code, "message": self.message, "details": self.details}
        if request_id:
            d["request_id"] = request_id
        return d


_DB_CODE = re.compile(r"FIN_([A-Z_]+):\s*(.*)")


def from_db_error(exc: Exception) -> Optional[FinError]:
    """Map a Postgres exception raised by a fin_ trigger to a FinError."""
    text = str(getattr(exc, "pgerror", None) or exc)
    m = _DB_CODE.search(text)
    if not m:
        return None
    code, message = m.group(1), m.group(2).splitlines()[0].strip()
    return FinError(code, message)


def not_found(what: str, ident: Any = None) -> FinError:
    return FinError("RESOURCE_NOT_FOUND", f"{what} not found" + (f": {ident}" if ident else ""))


def invalid(message: str, **details: Any) -> FinError:
    return FinError("VALIDATION_FAILED", message, details)
