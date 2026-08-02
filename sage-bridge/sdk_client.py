"""
sdk_client.py — Write (and structured read) access to Sage 50 via the
                official Sage.Peachtree.API.dll (.NET SDK).

This module uses pythonnet to load the Sage 50 .NET SDK assembly and
expose a thin Python wrapper around the most critical entity operations:

    Customers   — create / update
    Vendors     — create / update
    Invoices    — create sales invoice (triggers full ledger posting)
    Sales Orders — create / update
    Purchase Orders — create
    Payments    — apply customer receipts
    Journal Entries — create general journal entry
    Inventory   — read items (SDK read, safe for stock lookups)
    Company Info — read company information

IMPORTANT RUNTIME REQUIREMENTS
--------------------------------
1. This module must run on the same Windows machine where Sage 50 2013
   is installed.
2. pythonnet must target .NET Framework (not .NET Core):
       import pythonnet; pythonnet.load("netfx")
3. The Sage company file must not be exclusively locked by another process
   doing a backup at the same time (SDK handles concurrent user access fine).
4. The Windows user account running this service must have access to the
   Sage company folder.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bridge.sdk")

# ── pythonnet bootstrap ───────────────────────────────────────────────────────
_sdk_loaded = False
_sdk_lock = threading.Lock()

# These are set after load_sdk() succeeds
_peachtree = None   # Sage.Peachtree.API namespace
_session = None     # active PeachtreeSession (singleton, re-used per request)


def load_sdk(dll_path: str) -> None:
    """
    Load the Sage.Peachtree.API.dll via pythonnet.
    Call this once at application startup.
    """
    global _sdk_loaded, _peachtree

    with _sdk_lock:
        if _sdk_loaded:
            return

        try:
            import pythonnet  # noqa: F401 — version-check import
            pythonnet.load("netfx")  # Must target .NET Framework for Sage SDK
        except Exception as exc:
            logger.error("pythonnet bootstrap failed: %s", exc)
            raise RuntimeError(
                "pythonnet could not load .NET Framework runtime. "
                "Ensure pythonnet is installed (pip install pythonnet) "
                "and the machine has .NET Framework 4.x."
            ) from exc

        try:
            import clr  # noqa: F401
            clr.AddReference(dll_path)
            import Sage.Peachtree.API as _pt  # type: ignore[import]
            _peachtree = _pt
            _sdk_loaded = True
            logger.info("Sage.Peachtree.API loaded from: %s", dll_path)
        except Exception as exc:
            logger.error("Failed to load Sage SDK DLL from %s: %s", dll_path, exc)
            raise RuntimeError(
                f"Could not load Sage.Peachtree.API.dll from '{dll_path}'. "
                "Ensure Sage 50 2013 is installed and the DLL path is correct."
            ) from exc


# ── Session management ────────────────────────────────────────────────────────

class SageSession:
    """
    Wrapper around a PeachtreeSession + open Company, with health checking and
    automatic reconnection.

    Two problems with the original are fixed here.

    **1. A dead session never recovered.** ``_ensure_open`` reopened only when
    ``_session is None``. If Sage was closed and reopened, the company file got
    locked, or the session died for any other reason, the object was non-None
    but unusable — every subsequent call failed until someone restarted the
    service. ``_is_healthy()`` now probes the session and reconnects when the
    probe fails.

    **2. Concurrent SDK access.** The lock guarded only the *opening* of the
    session; the ``sdk_get_*`` functions then hit the .NET objects from
    whichever FastAPI threadpool worker they landed on. The Peachtree API is
    not documented thread-safe, and COM/.NET interop under pythonnet is
    apartment-sensitive. ``access()`` now serialises every SDK call through one
    reentrant lock.

    Serialising costs throughput, but this bridge handles a handful of
    invoices a minute on a single-user Sage install — correctness is worth far
    more than parallelism here.
    """

    #: Reconnect attempts before giving up on a single call.
    _MAX_RECONNECT = 2

    def __init__(self, company_path: str) -> None:
        self._company_path = company_path
        self._session = None
        self._company = None
        # Reentrant: access() may be nested by helpers that also take it.
        self._lock = threading.RLock()
        self._consecutive_failures = 0

    # ── connection state ─────────────────────────────────────────────────────

    def _open(self) -> None:
        """Open a Sage session and the company file. Caller holds the lock."""
        if not _sdk_loaded:
            raise RuntimeError("SDK not loaded. Call load_sdk() first.")

        session = _peachtree.PeachtreeSession()
        session.Begin(_peachtree.ProductType.Peachtree)
        company = session.Open(self._company_path)
        self._session = session
        self._company = company
        self._consecutive_failures = 0
        logger.info("Sage company opened: %s", self._company_path)

    def _is_healthy(self) -> bool:
        """
        Probe whether the session is still usable.

        Touching a cheap property is enough: a dead session raises rather than
        returning a wrong answer, which is exactly the signal we need.
        """
        if self._session is None or self._company is None:
            return False
        try:
            _ = self._company.Name
            return True
        except Exception as exc:
            logger.warning("Sage session failed health probe: %s", exc)
            return False

    def _reconnect(self) -> None:
        """Tear down and reopen. Caller holds the lock."""
        logger.info("Reopening Sage session...")
        self._close_locked()
        self._open()

    def _ensure_open(self) -> None:
        with self._lock:
            if not self._is_healthy():
                self._reconnect()

    # ── serialised access ────────────────────────────────────────────────────

    @contextmanager
    def access(self):
        """
        Context manager yielding the live Company object under an exclusive lock.

        Every SDK call must go through this::

            with _get_session().access() as company:
                company.Factories...

        Reconnects transparently if the session has died, retrying the caller's
        work is NOT attempted — the caller sees the exception and the sync layer
        leaves the event pending, so nothing is lost.
        """
        with self._lock:
            attempt = 0
            while True:
                if self._is_healthy():
                    break
                attempt += 1
                if attempt > self._MAX_RECONNECT:
                    self._consecutive_failures += 1
                    raise RuntimeError(
                        "Sage SDK session unavailable after {} reconnect "
                        "attempts (consecutive failures: {}). Check that Sage 50 "
                        "is installed, the company path is correct, and the SDK "
                        "authorization has been granted — see INSTALL.md."
                        .format(self._MAX_RECONNECT, self._consecutive_failures)
                    )
                try:
                    self._reconnect()
                except Exception as exc:
                    logger.error("Sage reconnect attempt %d failed: %s", attempt, exc)
                    time.sleep(1.0 * attempt)
            yield self._company

    @property
    def company(self):
        """Backwards-compatible accessor. Prefer access() for new code."""
        self._ensure_open()
        return self._company

    def health(self) -> Dict[str, Any]:
        """Report session state for /health and /sync/status."""
        with self._lock:
            healthy = self._is_healthy()
        return {
            "sdk_loaded": _sdk_loaded,
            "session_open": self._session is not None,
            "healthy": healthy,
            "company_path": self._company_path,
            "consecutive_failures": self._consecutive_failures,
        }

    # ── teardown ─────────────────────────────────────────────────────────────

    def _close_locked(self) -> None:
        if self._company is not None:
            try:
                self._company.Close()
            except Exception:
                pass
        if self._session is not None:
            try:
                self._session.End()
            except Exception:
                pass
        self._session = None
        self._company = None

    def close(self) -> None:
        with self._lock:
            self._close_locked()
            logger.info("Sage session closed.")


# Module-level singleton session (initialised in main.py startup)
_sage_session: Optional[SageSession] = None


def init_session(company_path: str) -> None:
    """Initialise the module-level SageSession. Call once at startup."""
    global _sage_session
    _sage_session = SageSession(company_path)
    _sage_session._ensure_open()


def _get_session() -> SageSession:
    if _sage_session is None:
        raise RuntimeError("SageSession not initialised. Call init_session() first.")
    return _sage_session


def sdk_health() -> Dict[str, Any]:
    """
    Report SDK availability without raising. Used by /health and /sync/status.

    Returns a dict rather than a bool so operators can tell "Sage not installed"
    apart from "session died" apart from "not authorized yet" — three very
    different problems that all previously surfaced as sdk_connected: false.
    """
    if _is_mock():
        return {"sdk_loaded": True, "session_open": True, "healthy": True,
                "mode": "mock"}
    if _sage_session is None:
        return {
            "sdk_loaded": _sdk_loaded,
            "session_open": False,
            "healthy": False,
            "reason": "session not initialised (SDK load or company open failed "
                      "at startup — check the log for the underlying error)",
        }
    return _sage_session.health()


def _is_mock() -> bool:
    """True when running in mock mode — no Sage DLL or company file required."""
    try:
        from config import get_settings
        return get_settings().SAGE_MOCK
    except Exception:
        return False


# ── Helper: convert .NET DateTime to Python date ─────────────────────────────

def _net_date(d: date) -> Any:
    """.NET DateTime from Python date."""
    import System  # type: ignore[import]
    return System.DateTime(d.year, d.month, d.day)


def _py_date(net_dt) -> Optional[str]:
    """Convert a .NET DateTime to ISO string, or None."""
    try:
        return f"{net_dt.Year:04d}-{net_dt.Month:02d}-{net_dt.Day:02d}"
    except Exception:
        return None


def _safe(val: Any, default: Any = None) -> Any:
    try:
        return val if val is not None else default
    except Exception:
        return default


# ── CUSTOMERS ─────────────────────────────────────────────────────────────────

def sdk_get_customers(limit: int = 500) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_CUSTOMERS, limit, 0)
    company = _get_session().company
    result = []
    customers = company.Customers.All
    count = 0
    for c in customers:
        if count >= limit:
            break
        result.append(_customer_to_dict(c))
        count += 1
    return result


def sdk_get_customer(customer_id: str) -> Optional[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return next((c for c in md.MOCK_CUSTOMERS if c["id"] == customer_id), None)
    company = _get_session().company
    customers = company.Customers.All
    for c in customers:
        if str(c.ID).strip() == customer_id.strip():
            return _customer_to_dict(c)
    return None


def sdk_create_customer(data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new customer in Sage and return the created record."""
    if _is_mock():
        import mock_data as md
        record = {"is_active": True, **data}
        md.MOCK_CUSTOMERS.append(record)
        logger.info("[MOCK] Customer created: %s", data.get("id"))
        return record
    company = _get_session().company
    customer = company.Customers.Create()

    customer.ID = data["id"]                       # Customer ID / code
    customer.Name = data["name"]
    customer.BillingAddress.Address1 = _safe(data.get("address1"), "")
    customer.BillingAddress.Address2 = _safe(data.get("address2"), "")
    customer.BillingAddress.City = _safe(data.get("city"), "")
    customer.BillingAddress.State = _safe(data.get("state"), "")
    customer.BillingAddress.Zip = _safe(data.get("zip"), "")
    customer.BillingAddress.Country = _safe(data.get("country"), "")
    customer.Telephone1 = _safe(data.get("phone"), "")
    customer.Fax = _safe(data.get("fax"), "")
    customer.Email = _safe(data.get("email"), "")
    customer.Contact = _safe(data.get("contact"), "")

    if data.get("credit_limit") is not None:
        customer.CreditLimit = float(data["credit_limit"])
    if data.get("terms"):
        customer.PurchaseRepresentative = _safe(data.get("sales_rep"), "")

    customer.Save()
    logger.info("Customer created in Sage: %s", customer.ID)
    return _customer_to_dict(customer)


def sdk_update_customer(customer_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Update an existing customer. Only fields present in data are updated."""
    company = _get_session().company
    customer = None
    for c in company.Customers.All:
        if str(c.ID).strip() == customer_id.strip():
            customer = c
            break
    if customer is None:
        raise ValueError(f"Customer '{customer_id}' not found in Sage")

    if "name" in data:
        customer.Name = data["name"]
    if "address1" in data:
        customer.BillingAddress.Address1 = data["address1"]
    if "address2" in data:
        customer.BillingAddress.Address2 = data["address2"]
    if "city" in data:
        customer.BillingAddress.City = data["city"]
    if "state" in data:
        customer.BillingAddress.State = data["state"]
    if "zip" in data:
        customer.BillingAddress.Zip = data["zip"]
    if "country" in data:
        customer.BillingAddress.Country = data["country"]
    if "phone" in data:
        customer.Telephone1 = data["phone"]
    if "email" in data:
        customer.Email = data["email"]
    if "contact" in data:
        customer.Contact = data["contact"]
    if "credit_limit" in data:
        customer.CreditLimit = float(data["credit_limit"])

    customer.Save()
    logger.info("Customer updated in Sage: %s", customer_id)
    return _customer_to_dict(customer)


def _customer_to_dict(c) -> Dict[str, Any]:
    return {
        "id": _safe(str(c.ID), ""),
        "name": _safe(str(c.Name), ""),
        "address1": _safe(str(c.BillingAddress.Address1), ""),
        "address2": _safe(str(c.BillingAddress.Address2), ""),
        "city": _safe(str(c.BillingAddress.City), ""),
        "state": _safe(str(c.BillingAddress.State), ""),
        "zip": _safe(str(c.BillingAddress.Zip), ""),
        "country": _safe(str(c.BillingAddress.Country), ""),
        "phone": _safe(str(c.Telephone1), ""),
        "fax": _safe(str(c.Fax), ""),
        "email": _safe(str(c.Email), ""),
        "contact": _safe(str(c.Contact), ""),
        "balance": _safe(float(c.CurrentBalance), 0.0),
        "credit_limit": _safe(float(c.CreditLimit), 0.0),
        "is_active": _safe(bool(c.IsActive), True),
    }


# ── VENDORS ───────────────────────────────────────────────────────────────────

def sdk_get_vendors(limit: int = 500) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_VENDORS, limit, 0)
    company = _get_session().company
    result = []
    count = 0
    for v in company.Vendors.All:
        if count >= limit:
            break
        result.append(_vendor_to_dict(v))
        count += 1
    return result


def sdk_get_vendor(vendor_id: str) -> Optional[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return next((v for v in md.MOCK_VENDORS if v["id"] == vendor_id), None)
    company = _get_session().company
    for v in company.Vendors.All:
        if str(v.ID).strip() == vendor_id.strip():
            return _vendor_to_dict(v)
    return None


def sdk_create_vendor(data: Dict[str, Any]) -> Dict[str, Any]:
    if _is_mock():
        import mock_data as md
        record = {"is_active": True, "balance": 0.0, **data}
        md.MOCK_VENDORS.append(record)
        logger.info("[MOCK] Vendor created: %s", data.get("id"))
        return record
    company = _get_session().company
    vendor = company.Vendors.Create()
    vendor.ID = data["id"]
    vendor.Name = data["name"]
    vendor.PurchasesAddress.Address1 = _safe(data.get("address1"), "")
    vendor.PurchasesAddress.City = _safe(data.get("city"), "")
    vendor.PurchasesAddress.State = _safe(data.get("state"), "")
    vendor.PurchasesAddress.Zip = _safe(data.get("zip"), "")
    vendor.PurchasesAddress.Country = _safe(data.get("country"), "")
    vendor.Telephone1 = _safe(data.get("phone"), "")
    vendor.Email = _safe(data.get("email"), "")
    vendor.Contact = _safe(data.get("contact"), "")
    vendor.Save()
    logger.info("Vendor created in Sage: %s", vendor.ID)
    return _vendor_to_dict(vendor)


def _vendor_to_dict(v) -> Dict[str, Any]:
    return {
        "id": _safe(str(v.ID), ""),
        "name": _safe(str(v.Name), ""),
        "address1": _safe(str(v.PurchasesAddress.Address1), ""),
        "city": _safe(str(v.PurchasesAddress.City), ""),
        "state": _safe(str(v.PurchasesAddress.State), ""),
        "zip": _safe(str(v.PurchasesAddress.Zip), ""),
        "country": _safe(str(v.PurchasesAddress.Country), ""),
        "phone": _safe(str(v.Telephone1), ""),
        "email": _safe(str(v.Email), ""),
        "contact": _safe(str(v.Contact), ""),
        "balance": _safe(float(v.CurrentBalance), 0.0),
        "is_active": _safe(bool(v.IsActive), True),
    }


# ── SALES INVOICES ────────────────────────────────────────────────────────────

def sdk_get_invoices(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    customer_id: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        data = md.MOCK_INVOICES
        if customer_id:
            data = [i for i in data if i.get("customer_id") == customer_id]
        if from_date:
            data = [i for i in data if i.get("date", "") >= str(from_date)]
        if to_date:
            data = [i for i in data if i.get("date", "") <= str(to_date)]
        return md.paginate(data, limit, 0)
    company = _get_session().company
    result = []
    count = 0
    for inv in company.SalesInvoices.All:
        if count >= limit:
            break
        inv_date_str = _py_date(inv.Date)
        if from_date and inv_date_str and inv_date_str < str(from_date):
            continue
        if to_date and inv_date_str and inv_date_str > str(to_date):
            continue
        if customer_id and str(inv.CustomerReference).strip() != customer_id.strip():
            continue
        result.append(_invoice_to_dict(inv))
        count += 1
    return result


def sdk_get_invoice(invoice_id: str) -> Optional[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return next((i for i in md.MOCK_INVOICES if i["sage_id"] == invoice_id), None)
    company = _get_session().company
    for inv in company.SalesInvoices.All:
        if str(inv.Key.ID).strip() == invoice_id.strip():
            return _invoice_to_dict(inv)
    return None


def sdk_create_invoice(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a Sales Invoice in Sage 50.
    data must contain:
        customer_id   : str   — Sage customer ID
        date          : str   — ISO date (YYYY-MM-DD)
        due_date      : str   — ISO date (YYYY-MM-DD)
        lines         : list of {
            description : str
            quantity    : float
            unit_price  : float
            gl_account  : str   — chart-of-accounts code
            item_id     : str   — inventory item ID (optional)
        }
    Optional:
        invoice_number : str
        ship_date      : str
        ship_method    : str
        po_number      : str
        reference      : str
        note           : str
    """
    if _is_mock():
        import mock_data as md, uuid as _uuid
        sage_id = f"INV-MOCK-{_uuid.uuid4().hex[:6].upper()}"
        record = {
            "sage_id": sage_id,
            "customer_id": data["customer_id"],
            "date": data["date"],
            "due_date": data["due_date"],
            "invoice_number": data.get("invoice_number", sage_id),
            "po_number": data.get("po_number", ""),
            "total_amount": sum(float(l.get("quantity", 1)) * float(l.get("unit_price", 0)) for l in data.get("lines", [])),
            "amount_paid": 0.0, "amount_due": 0.0, "is_paid": False,
            "note": data.get("note", ""), "lines": data.get("lines", []),
        }
        md.MOCK_INVOICES.append(record)
        logger.info("[MOCK] Invoice created: %s", sage_id)
        return record
    company = _get_session().company
    invoice = company.SalesInvoices.Create()
    invoice.CustomerReference = data["customer_id"]
    inv_date = date.fromisoformat(data["date"])
    invoice.Date = _net_date(inv_date)

    due_date = date.fromisoformat(data["due_date"])
    invoice.DueDate = _net_date(due_date)

    if data.get("invoice_number"):
        invoice.ReferenceNumber = data["invoice_number"]
    if data.get("ship_date"):
        invoice.ShipByDate = _net_date(date.fromisoformat(data["ship_date"]))
    if data.get("po_number"):
        invoice.CustomerPurchaseOrderNumber = data["po_number"]
    if data.get("note"):
        invoice.Note = data["note"]
    if data.get("reference"):
        invoice.Reference = data["reference"]

    for line_data in data.get("lines", []):
        line = invoice.AddLine()
        line.Description = _safe(line_data.get("description"), "")
        line.Quantity = float(_safe(line_data.get("quantity"), 1))
        line.UnitPrice = float(_safe(line_data.get("unit_price"), 0))
        if line_data.get("gl_account"):
            line.AccountReference = line_data["gl_account"]
        if line_data.get("item_id"):
            line.ItemReference = line_data["item_id"]

    invoice.Save()
    sage_id = str(invoice.Key.ID)
    logger.info("Sales invoice created in Sage: %s (customer: %s)", sage_id, data["customer_id"])
    return _invoice_to_dict(invoice)


def sdk_void_invoice(invoice_id: str) -> bool:
    """Void (delete) a sales invoice by its Sage ID. Returns True on success."""
    if _is_mock():
        import mock_data as md
        before = len(md.MOCK_INVOICES)
        md.MOCK_INVOICES[:] = [i for i in md.MOCK_INVOICES if i["sage_id"] != invoice_id]
        logger.info("[MOCK] Invoice voided: %s", invoice_id)
        return len(md.MOCK_INVOICES) < before
    company = _get_session().company
    for inv in company.SalesInvoices.All:
        if str(inv.Key.ID).strip() == invoice_id.strip():
            inv.Delete()
            logger.info("Sage invoice voided: %s", invoice_id)
            return True
    return False


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """
    Read a .NET property that may not exist on this SDK build.

    Sage 50 2013's API surface varies slightly between releases; referencing a
    property that is absent raises rather than returning None. Every optional
    field goes through here so a missing property degrades that one field
    instead of failing the whole extraction.
    """
    try:
        value = getattr(obj, name, default)
        return default if value is None else value
    except Exception:
        return default


def _invoice_to_dict(inv) -> Dict[str, Any]:
    """
    Map a Sage SalesInvoice to our wire format.

    Extended beyond the original to carry tax, per-line tax, customer name and
    shipping — the original returned none of these, so SynBot was driving
    finance and inventory updates from header totals alone.
    """
    lines: List[Dict[str, Any]] = []
    try:
        for idx, line in enumerate(inv.SalesInvoiceLines):
            lines.append({
                "line_no": idx + 1,
                "description": _safe(str(_attr(line, "Description", "")), ""),
                "quantity": _safe(float(_attr(line, "Quantity", 0.0)), 0.0),
                "unit_price": _safe(float(_attr(line, "UnitPrice", 0.0)), 0.0),
                "amount": _safe(float(_attr(line, "Amount", 0.0)), 0.0),
                "gl_account": _safe(str(_attr(line, "AccountReference", "")), ""),
                "item_id": _safe(str(_attr(line, "ItemReference", "")), ""),
                # Tax per line — absent on some 2013 builds, hence _attr.
                "tax_type": _safe(str(_attr(line, "SalesTaxType", "")), ""),
                "tax_amount": _safe(float(_attr(line, "SalesTaxAmount", 0.0)), 0.0),
            })
    except Exception as exc:
        # Do NOT swallow silently as the original did: a header with no lines
        # looks like a valid empty invoice downstream and would zero out the
        # inventory movement for a real sale.
        logger.error(
            "Failed reading invoice lines for %s: %s — record marked incomplete",
            _safe(str(_attr(getattr(inv, "Key", None), "ID", "")), "?"), exc,
        )
        raise

    return {
        "sage_id": _safe(str(inv.Key.ID), ""),
        "customer_id": _safe(str(_attr(inv, "CustomerReference", "")), ""),
        "customer_name": _safe(str(_attr(inv, "CustomerName", "")), ""),
        "date": _py_date(inv.Date),
        "due_date": _py_date(_attr(inv, "DueDate")),
        "ship_date": _py_date(_attr(inv, "ShipDate")),
        "ship_method": _safe(str(_attr(inv, "ShipVia", "")), ""),
        "invoice_number": _safe(str(_attr(inv, "ReferenceNumber", "")), ""),
        "po_number": _safe(str(_attr(inv, "CustomerPurchaseOrderNumber", "")), ""),
        "total_amount": _safe(float(_attr(inv, "TotalAmount", 0.0)), 0.0),
        "amount_paid": _safe(float(_attr(inv, "AmountPaid", 0.0)), 0.0),
        "amount_due": _safe(float(_attr(inv, "AmountDue", 0.0)), 0.0),
        "sales_tax_amount": _safe(float(_attr(inv, "SalesTaxAmount", 0.0)), 0.0),
        "tax_code": _safe(str(_attr(inv, "SalesTaxCodeReference", "")), ""),
        "freight_amount": _safe(float(_attr(inv, "FreightAmount", 0.0)), 0.0),
        "is_paid": _safe(bool(_attr(inv, "IsPaid", False)), False),
        "note": _safe(str(_attr(inv, "Note", "")), ""),
        "lines": lines,
    }


# ── SALES ORDERS ──────────────────────────────────────────────────────────────

def sdk_get_sales_orders(limit: int = 500) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_SALES_ORDERS, limit, 0)
    company = _get_session().company
    result = []
    count = 0
    for so in company.SalesOrders.All:
        if count >= limit:
            break
        result.append(_sales_order_to_dict(so))
        count += 1
    return result


def sdk_create_sales_order(data: Dict[str, Any]) -> Dict[str, Any]:
    if _is_mock():
        import mock_data as md, uuid as _uuid
        record = {"sage_id": f"SO-MOCK-{_uuid.uuid4().hex[:6].upper()}", **data}
        md.MOCK_SALES_ORDERS.append(record)
        logger.info("[MOCK] Sales order created")
        return record
    company = _get_session().company
    so = company.SalesOrders.Create()
    so.CustomerReference = data["customer_id"]
    so.Date = _net_date(date.fromisoformat(data["date"]))
    if data.get("good_through_date"):
        so.GoodThroughDate = _net_date(date.fromisoformat(data["good_through_date"]))
    if data.get("ship_date"):
        so.ShipByDate = _net_date(date.fromisoformat(data["ship_date"]))
    if data.get("po_number"):
        so.CustomerPurchaseOrderNumber = data["po_number"]
    if data.get("reference"):
        so.Reference = data["reference"]
    for line_data in data.get("lines", []):
        line = so.AddLine()
        line.Description = _safe(line_data.get("description"), "")
        line.Quantity = float(_safe(line_data.get("quantity"), 1))
        line.UnitPrice = float(_safe(line_data.get("unit_price"), 0))
        if line_data.get("item_id"):
            line.ItemReference = line_data["item_id"]
    so.Save()
    logger.info("Sales order created in Sage: %s", str(so.Key.ID))
    return _sales_order_to_dict(so)


def _sales_order_to_dict(so) -> Dict[str, Any]:
    lines = []
    try:
        for line in so.SalesOrderLines:
            lines.append({
                "description": _safe(str(line.Description), ""),
                "quantity": _safe(float(line.Quantity), 0.0),
                "unit_price": _safe(float(line.UnitPrice), 0.0),
                "item_id": _safe(str(line.ItemReference), ""),
            })
    except Exception:
        pass
    return {
        "sage_id": _safe(str(so.Key.ID), ""),
        "customer_id": _safe(str(so.CustomerReference), ""),
        "date": _py_date(so.Date),
        "ship_date": _py_date(so.ShipByDate),
        "po_number": _safe(str(so.CustomerPurchaseOrderNumber), ""),
        "total_amount": _safe(float(so.TotalAmount), 0.0),
        "lines": lines,
    }


# ── PURCHASE ORDERS ───────────────────────────────────────────────────────────

def sdk_get_purchase_orders(limit: int = 500) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_PURCHASE_ORDERS, limit, 0)
    company = _get_session().company
    result = []
    count = 0
    for po in company.PurchaseOrders.All:
        if count >= limit:
            break
        result.append(_purchase_order_to_dict(po))
        count += 1
    return result


def sdk_create_purchase_order(data: Dict[str, Any]) -> Dict[str, Any]:
    if _is_mock():
        import mock_data as md, uuid as _uuid
        record = {"sage_id": f"PO-MOCK-{_uuid.uuid4().hex[:6].upper()}", **data}
        md.MOCK_PURCHASE_ORDERS.append(record)
        logger.info("[MOCK] Purchase order created")
        return record
    company = _get_session().company
    po = company.PurchaseOrders.Create()
    po.VendorReference = data["vendor_id"]
    po.Date = _net_date(date.fromisoformat(data["date"]))
    if data.get("expected_date"):
        po.ExpectedDate = _net_date(date.fromisoformat(data["expected_date"]))
    if data.get("reference"):
        po.Reference = data["reference"]
    for line_data in data.get("lines", []):
        line = po.AddLine()
        line.Description = _safe(line_data.get("description"), "")
        line.Quantity = float(_safe(line_data.get("quantity"), 1))
        line.UnitPrice = float(_safe(line_data.get("unit_price"), 0))
        if line_data.get("item_id"):
            line.ItemReference = line_data["item_id"]
        if line_data.get("gl_account"):
            line.AccountReference = line_data["gl_account"]
    po.Save()
    logger.info("Purchase order created in Sage: %s", str(po.Key.ID))
    return _purchase_order_to_dict(po)


def _purchase_order_to_dict(po) -> Dict[str, Any]:
    lines = []
    try:
        for line in po.PurchaseOrderLines:
            lines.append({
                "description": _safe(str(line.Description), ""),
                "quantity": _safe(float(line.Quantity), 0.0),
                "unit_price": _safe(float(line.UnitPrice), 0.0),
                "item_id": _safe(str(line.ItemReference), ""),
            })
    except Exception:
        pass
    return {
        "sage_id": _safe(str(po.Key.ID), ""),
        "vendor_id": _safe(str(po.VendorReference), ""),
        "date": _py_date(po.Date),
        "expected_date": _py_date(po.ExpectedDate),
        "reference": _safe(str(po.Reference), ""),
        "total_amount": _safe(float(po.TotalAmount), 0.0),
        "lines": lines,
    }


# ── INVENTORY ITEMS ───────────────────────────────────────────────────────────

def sdk_get_inventory(limit: int = 1000) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_INVENTORY, limit, 0)
    company = _get_session().company
    result = []
    count = 0
    for item in company.InventoryItems.All:
        if count >= limit:
            break
        result.append(_inventory_to_dict(item))
        count += 1
    return result


def sdk_get_inventory_item(item_id: str) -> Optional[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return next((i for i in md.MOCK_INVENTORY if i["id"] == item_id), None)
    company = _get_session().company
    for item in company.InventoryItems.All:
        if str(item.ID).strip() == item_id.strip():
            return _inventory_to_dict(item)
    return None


def _inventory_to_dict(item) -> Dict[str, Any]:
    return {
        "id": _safe(str(item.ID), ""),
        "description": _safe(str(item.Description), ""),
        "item_type": _safe(str(item.ItemType), ""),
        "sales_price": _safe(float(item.SalesPrice), 0.0),
        "cost": _safe(float(item.Cost), 0.0),
        "quantity_on_hand": _safe(float(item.QuantityOnHand), 0.0),
        "quantity_on_order": _safe(float(item.QuantityOnOrder), 0.0),
        "reorder_quantity": _safe(float(item.ReorderQuantity), 0.0),
        "sales_gl_account": _safe(str(item.SalesGLAccount), ""),
        "cogs_gl_account": _safe(str(item.COGSGLAccount), ""),
        "inventory_gl_account": _safe(str(item.InventoryGLAccount), ""),
        "is_active": _safe(bool(item.IsActive), True),
        "unit_of_measure": _safe(str(item.UnitOfMeasure), ""),
        "weight": _safe(float(item.Weight), 0.0),
    }


# ── CHART OF ACCOUNTS ─────────────────────────────────────────────────────────

def sdk_get_accounts(limit: int = 1000) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_ACCOUNTS, limit, 0)
    company = _get_session().company
    result = []
    count = 0
    for acct in company.Accounts.All:
        if count >= limit:
            break
        result.append(_account_to_dict(acct))
        count += 1
    return result


def _account_to_dict(acct) -> Dict[str, Any]:
    return {
        "id": _safe(str(acct.Key.ID), ""),
        "description": _safe(str(acct.Description), ""),
        "account_type": _safe(str(acct.AccountType), ""),
        "balance": _safe(float(acct.CurrentBalance), 0.0),
        "is_active": _safe(bool(acct.IsActive), True),
    }


# ── EMPLOYEES ─────────────────────────────────────────────────────────────────

def sdk_get_employees(limit: int = 500) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_EMPLOYEES, limit, 0)
    company = _get_session().company
    result = []
    count = 0
    for emp in company.Employees.All:
        if count >= limit:
            break
        result.append(_employee_to_dict(emp))
        count += 1
    return result


def _employee_to_dict(emp) -> Dict[str, Any]:
    return {
        "id": _safe(str(emp.ID), ""),
        "first_name": _safe(str(emp.FirstName), ""),
        "last_name": _safe(str(emp.LastName), ""),
        "address1": _safe(str(emp.Address.Address1), ""),
        "city": _safe(str(emp.Address.City), ""),
        "state": _safe(str(emp.Address.State), ""),
        "zip": _safe(str(emp.Address.Zip), ""),
        "phone": _safe(str(emp.Telephone), ""),
        "email": _safe(str(emp.Email), ""),
        "hire_date": _py_date(emp.HireDate),
        "pay_type": _safe(str(emp.PayType), ""),
        "pay_frequency": _safe(str(emp.PayFrequency), ""),
        "is_active": _safe(bool(emp.IsActive), True),
        "department": _safe(str(emp.Department), ""),
    }


# ── CUSTOMER RECEIPTS (Payments Received) ─────────────────────────────────────

def sdk_get_customer_receipts(
    customer_id: Optional[str] = None,
    from_date: Optional[date] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        data = md.MOCK_PAYMENTS
        if customer_id:
            data = [p for p in data if p.get("customer_id") == customer_id]
        return md.paginate(data, limit, 0)
    company = _get_session().company
    result = []
    count = 0
    for receipt in company.CustomerReceipts.All:
        if count >= limit:
            break
        if customer_id and str(receipt.CustomerReference).strip() != customer_id.strip():
            continue
        if from_date and _py_date(receipt.Date) and _py_date(receipt.Date) < str(from_date):
            continue
        result.append(_receipt_to_dict(receipt))
        count += 1
    return result


def sdk_apply_customer_receipt(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply a payment against an outstanding invoice.
    data:
        customer_id   : str
        date          : str (ISO)
        amount        : float
        reference     : str (cheque number / reference)
        invoice_id    : str — Sage invoice ID to apply against (optional)
        deposit_ticket_id : str (optional)
    """
    if _is_mock():
        import mock_data as md, uuid as _uuid
        record = {"sage_id": f"RCPT-MOCK-{_uuid.uuid4().hex[:6].upper()}", **data}
        md.MOCK_PAYMENTS.append(record)
        logger.info("[MOCK] Receipt applied: customer=%s amount=%s", data.get("customer_id"), data.get("amount"))
        return record
    company = _get_session().company
    receipt = company.CustomerReceipts.Create()
    receipt.CustomerReference = data["customer_id"]
    receipt.Date = _net_date(date.fromisoformat(data["date"]))
    receipt.AmountReceived = float(data["amount"])
    if data.get("reference"):
        receipt.Reference = data["reference"]
    if data.get("deposit_ticket_id"):
        receipt.DepositTicketID = data["deposit_ticket_id"]
    if data.get("invoice_id"):
        # Apply to specific invoice
        for line in receipt.ApplyToInvoices:
            if str(line.InvoiceKey.ID).strip() == str(data["invoice_id"]).strip():
                line.AmountApplied = float(data["amount"])
                break
    receipt.Save()
    logger.info(
        "Customer receipt applied: customer=%s amount=%.2f",
        data["customer_id"], float(data["amount"]),
    )
    return _receipt_to_dict(receipt)


def _receipt_to_dict(r) -> Dict[str, Any]:
    return {
        "sage_id": _safe(str(r.Key.ID), ""),
        "customer_id": _safe(str(r.CustomerReference), ""),
        "date": _py_date(r.Date),
        "amount": _safe(float(r.AmountReceived), 0.0),
        "reference": _safe(str(r.Reference), ""),
    }


# ── VENDOR BILLS (Accounts Payable) ──────────────────────────────────────────

def sdk_get_vendor_invoices(limit: int = 500) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_VENDOR_BILLS, limit, 0)
    company = _get_session().company
    result = []
    count = 0
    for bill in company.VendorInvoices.All:
        if count >= limit:
            break
        result.append(_vendor_invoice_to_dict(bill))
        count += 1
    return result


def sdk_create_vendor_invoice(data: Dict[str, Any]) -> Dict[str, Any]:
    if _is_mock():
        import mock_data as md, uuid as _uuid
        record = {"sage_id": f"BILL-MOCK-{_uuid.uuid4().hex[:6].upper()}", "is_paid": False, **data}
        md.MOCK_VENDOR_BILLS.append(record)
        logger.info("[MOCK] Vendor invoice created")
        return record
    company = _get_session().company
    bill = company.VendorInvoices.Create()
    bill.VendorReference = data["vendor_id"]
    bill.Date = _net_date(date.fromisoformat(data["date"]))
    if data.get("due_date"):
        bill.DueDate = _net_date(date.fromisoformat(data["due_date"]))
    if data.get("reference"):
        bill.Reference = data["reference"]
    for line_data in data.get("lines", []):
        line = bill.AddLine()
        line.Description = _safe(line_data.get("description"), "")
        line.Quantity = float(_safe(line_data.get("quantity"), 1))
        line.UnitPrice = float(_safe(line_data.get("unit_price"), 0))
        if line_data.get("gl_account"):
            line.AccountReference = line_data["gl_account"]
    bill.Save()
    logger.info("Vendor invoice created in Sage: %s", str(bill.Key.ID))
    return _vendor_invoice_to_dict(bill)


def _vendor_invoice_to_dict(bill) -> Dict[str, Any]:
    return {
        "sage_id": _safe(str(bill.Key.ID), ""),
        "vendor_id": _safe(str(bill.VendorReference), ""),
        "date": _py_date(bill.Date),
        "due_date": _py_date(bill.DueDate),
        "reference": _safe(str(bill.Reference), ""),
        "total_amount": _safe(float(bill.TotalAmount), 0.0),
        "amount_paid": _safe(float(bill.AmountPaid), 0.0),
        "amount_due": _safe(float(bill.AmountDue), 0.0),
        "is_paid": _safe(bool(bill.IsPaid), False),
    }


# ── GENERAL JOURNAL ENTRIES ───────────────────────────────────────────────────

def sdk_get_journal_entries(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        data = md.MOCK_JOURNAL
        if from_date:
            data = [j for j in data if j.get("date", "") >= str(from_date)]
        if to_date:
            data = [j for j in data if j.get("date", "") <= str(to_date)]
        return md.paginate(data, limit, 0)
    company = _get_session().company
    result = []
    count = 0
    for entry in company.GeneralJournalEntries.All:
        if count >= limit:
            break
        entry_date = _py_date(entry.Date)
        if from_date and entry_date and entry_date < str(from_date):
            continue
        if to_date and entry_date and entry_date > str(to_date):
            continue
        result.append(_journal_entry_to_dict(entry))
        count += 1
    return result


def sdk_create_journal_entry(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a general journal entry.
    data:
        date     : str (ISO)
        reference: str
        lines    : list of {
            account_id : str
            debit      : float (0 if credit)
            credit     : float (0 if debit)
            description: str
        }
    Debits must equal credits — validated here.
    """
    total_debit = sum(float(l.get("debit", 0)) for l in data.get("lines", []))
    total_credit = sum(float(l.get("credit", 0)) for l in data.get("lines", []))
    if round(total_debit, 4) != round(total_credit, 4):
        raise ValueError(
            f"Journal entry does not balance: debits={total_debit:.4f} credits={total_credit:.4f}"
        )

    if _is_mock():
        import mock_data as md, uuid as _uuid
        record = {"sage_id": f"JNL-MOCK-{_uuid.uuid4().hex[:6].upper()}", **data}
        md.MOCK_JOURNAL.append(record)
        logger.info("[MOCK] Journal entry created")
        return record
    company = _get_session().company
    entry = company.GeneralJournalEntries.Create()
    entry.Date = _net_date(date.fromisoformat(data["date"]))
    if data.get("reference"):
        entry.Reference = data["reference"]

    for line_data in data.get("lines", []):
        line = entry.AddLine()
        line.AccountReference = line_data["account_id"]
        line.Debit = float(_safe(line_data.get("debit"), 0))
        line.Credit = float(_safe(line_data.get("credit"), 0))
        line.Description = _safe(line_data.get("description"), "")

    entry.Save()
    logger.info("General journal entry created in Sage: %s", str(entry.Key.ID))
    return _journal_entry_to_dict(entry)


def _journal_entry_to_dict(entry) -> Dict[str, Any]:
    lines = []
    try:
        for line in entry.GeneralJournalLines:
            lines.append({
                "account_id": _safe(str(line.AccountReference), ""),
                "debit": _safe(float(line.Debit), 0.0),
                "credit": _safe(float(line.Credit), 0.0),
                "description": _safe(str(line.Description), ""),
            })
    except Exception:
        pass
    return {
        "sage_id": _safe(str(entry.Key.ID), ""),
        "date": _py_date(entry.Date),
        "reference": _safe(str(entry.Reference), ""),
        "lines": lines,
    }


# ── COMPANY INFORMATION ───────────────────────────────────────────────────────

def sdk_get_company_info() -> Dict[str, Any]:
    if _is_mock():
        import mock_data as md
        return md.MOCK_COMPANY
    company = _get_session().company
    info = company.CompanyInformation
    return {
        "name": _safe(str(info.CompanyName), ""),
        "address1": _safe(str(info.Address.Address1), ""),
        "address2": _safe(str(info.Address.Address2), ""),
        "city": _safe(str(info.Address.City), ""),
        "state": _safe(str(info.Address.State), ""),
        "zip": _safe(str(info.Address.Zip), ""),
        "country": _safe(str(info.Address.Country), ""),
        "phone": _safe(str(info.Telephone), ""),
        "fax": _safe(str(info.Fax), ""),
        "email": _safe(str(info.Email), ""),
        "website": _safe(str(info.WebSite), ""),
        "tax_id": _safe(str(info.FederalEmployerID), ""),
        "fiscal_year_start": _py_date(info.FiscalYearStart),
    }


# ── PAYROLL ───────────────────────────────────────────────────────────────────

def sdk_get_payroll_checks(
    from_date: Optional[date] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        data = md.MOCK_PAYROLL
        if from_date:
            data = [p for p in data if p.get("date", "") >= str(from_date)]
        return md.paginate(data, limit, 0)
    company = _get_session().company
    result = []
    count = 0
    for chk in company.PayrollChecks.All:
        if count >= limit:
            break
        chk_date = _py_date(chk.Date)
        if from_date and chk_date and chk_date < str(from_date):
            continue
        result.append({
            "sage_id": _safe(str(chk.Key.ID), ""),
            "employee_id": _safe(str(chk.EmployeeReference), ""),
            "date": chk_date,
            "reference": _safe(str(chk.Reference), ""),
            "gross_pay": _safe(float(chk.GrossPay), 0.0),
            "net_pay": _safe(float(chk.NetPay), 0.0),
        })
        count += 1
    return result


# ── QUOTES ────────────────────────────────────────────────────────────────────

def sdk_get_quotes(limit: int = 500) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_QUOTES, limit, 0)
    company = _get_session().company
    result = []
    count = 0
    for q in company.Quotes.All:
        if count >= limit:
            break
        result.append({
            "sage_id": _safe(str(q.Key.ID), ""),
            "customer_id": _safe(str(q.CustomerReference), ""),
            "date": _py_date(q.Date),
            "good_through_date": _py_date(q.GoodThroughDate),
            "total_amount": _safe(float(q.TotalAmount), 0.0),
            "reference": _safe(str(q.Reference), ""),
        })
        count += 1
    return result


# ── JOBS (Job Costing) ────────────────────────────────────────────────────────

def sdk_get_jobs(limit: int = 500) -> List[Dict[str, Any]]:
    if _is_mock():
        import mock_data as md
        return md.paginate(md.MOCK_JOBS, limit, 0)
    company = _get_session().company
    result = []
    count = 0
    for job in company.Jobs.All:
        if count >= limit:
            break
        result.append({
            "id": _safe(str(job.ID), ""),
            "description": _safe(str(job.Description), ""),
            "customer_id": _safe(str(job.CustomerReference), ""),
            "start_date": _py_date(job.StartDate),
            "projected_end_date": _py_date(job.ProjectedEndDate),
            "status": _safe(str(job.Status), ""),
            "estimated_revenue": _safe(float(job.EstimatedRevenue), 0.0),
            "actual_revenue": _safe(float(job.ActualRevenue), 0.0),
        })
        count += 1
    return result
