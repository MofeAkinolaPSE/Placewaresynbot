"""
sdk_api.py — The real Sage 50 2013 SDK surface, verified by reflection.

WHY THIS FILE EXISTS
--------------------
``sdk_client.py`` was originally written against an API that does not exist in
Sage.Peachtree.API 2013.0.0.826. Verified against the shipped assembly:

    what the old code called          what the assembly actually exposes
    --------------------------------  ------------------------------------------
    session.Begin(ProductType.X)      Begin(String applicationIdentifier)
                                      — there is no ProductType type at all
    session.Open("C:\\path\\to\\co")   Open(CompanyIdentifier)
    company.SalesInvoices.All         company.Factories.SalesInvoiceFactory.List()
    company.Customers / .Vendors /    none of these exist. Company exposes
      .InventoryItems / .Accounts /   exactly: CompanyIdentifier, Defaults,
      .Employees / .Quotes / ...      Factories, IsClosed, Services
    company.Close()                   session.Close(company)
    invoice.TotalAmount / .AmountPaid Amount / (Amount - AmountDue)
    invoice.SalesInvoiceLines         invoice.ApplyToSalesLines
    line.ItemReference                line.InventoryItemReference
    customer.BillingAddress           customer.BillToContact.Address
    customer.CurrentBalance           customer.Balance
    customer.IsActive                 not IsInactive

None of that would have failed at load time. It would have failed at the first
real call, been caught by main.py's degraded-start handler, and left the bridge
running ODBC-only — every invoice arriving as ``completeness=partial`` with no
tax, and every write path dead. Silently, because the fail-soft path is working
as designed.

This module isolates the true API so the mapping is in one auditable place.

WHAT IS AND IS NOT VERIFIED
---------------------------
Every type name, property name, method name and signature below was read out of
the shipped assembly by reflection. They are correct.

What could NOT be checked without a company file: whether the *values* are what
we expect (a property can exist and still be empty, or mean something subtler
than its name suggests), and whether the load/filter strategy performs
acceptably on a company with years of history. Those need the client machine.
"""
from __future__ import annotations

import datetime
import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bridge.sdk.api")


# ── value coercion ───────────────────────────────────────────────────────────

def text(value: Any, default: str = "") -> str:
    """Coerce a CLR string to a trimmed Python str. Never raises."""
    if value is None:
        return default
    try:
        return str(value).strip()
    except Exception:
        return default


def num(value: Any, default: float = 0.0) -> float:
    """
    Coerce a CLR Decimal to float. Never raises.

    Sage money is System.Decimal. float() on it works through pythonnet, but a
    null (unset Nullable) must not become 0.0 silently where the caller cares —
    callers that care pass an explicit default.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def iso_date(value: Any) -> Optional[str]:
    """
    Convert a CLR DateTime (or Nullable<DateTime>) to ISO YYYY-MM-DD.

    Nullable date properties — DateDue, ShipByDate, LastInvoiceDate — come
    through as None when unset, so this returns None rather than inventing an
    epoch date.
    """
    if value is None:
        return None
    try:
        return "{:04d}-{:02d}-{:02d}".format(value.Year, value.Month, value.Day)
    except Exception:
        pass
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.strftime("%Y-%m-%d")
    return None


def net_datetime(day: datetime.date):
    """Build a System.DateTime from a Python date."""
    import System  # type: ignore[import]
    return System.DateTime(day.year, day.month, day.day)


# ── EntityReference resolution ───────────────────────────────────────────────
#
# Sage models every foreign key as EntityReference<T>, which carries only a
# Guid — not the human-readable ID. Getting "CUST001" out of
# invoice.CustomerReference means loading the referenced entity:
#
#     invoice.CustomerReference.Load(company).ID
#
# That is a database round trip per reference, and an invoice has several
# (customer, tax code, each line's account and inventory item). Resolving them
# naively is O(lines) round trips per invoice, which on Pervasive over old
# hardware is the difference between a sync that keeps up and one that does not.
#
# Hence the cache below. It is keyed on the reference Guid and lives for the
# process, because these are dimension records: a customer's ID does not change
# under us, and if one is renamed the bridge restarts rarely enough that a
# stale display value is a far smaller problem than the round trips.

_ref_cache: Dict[str, Dict[str, str]] = {}
_ref_cache_lock = threading.Lock()

#: Bound on the cache so a company with a very large item catalogue cannot grow
#: it without limit on a memory-constrained box.
_REF_CACHE_MAX = 5000


def resolve_reference(company, reference) -> Dict[str, str]:
    """
    Resolve an EntityReference to ``{"id": ..., "name": ...}``.

    Returns empty strings when the reference is unset or cannot be loaded — a
    missing dimension must degrade that one field, never fail the extraction of
    an otherwise good invoice.
    """
    if reference is None:
        return {"id": "", "name": ""}
    try:
        if reference.IsEmpty:
            return {"id": "", "name": ""}
        guid = str(reference.Guid)
    except Exception:
        return {"id": "", "name": ""}

    with _ref_cache_lock:
        hit = _ref_cache.get(guid)
    if hit is not None:
        return hit

    result = {"id": "", "name": ""}
    try:
        entity = reference.Load(company)
        if entity is not None:
            result = {
                "id": text(getattr(entity, "ID", "")),
                "name": text(getattr(entity, "Name", "")),
            }
    except Exception as exc:
        logger.debug("Could not resolve reference %s: %s", guid, exc)

    with _ref_cache_lock:
        if len(_ref_cache) < _REF_CACHE_MAX:
            _ref_cache[guid] = result
    return result


def reference_id(company, reference) -> str:
    """Just the human-readable ID of a reference."""
    return resolve_reference(company, reference)["id"]


def clear_reference_cache() -> None:
    """Drop cached reference lookups. Called when a session is reopened."""
    with _ref_cache_lock:
        _ref_cache.clear()


# ── entity list loading ──────────────────────────────────────────────────────

def load_list(entity_list, limit: Optional[int] = None) -> List[Any]:
    """
    Populate and materialise an EntityList.

    ``factory.List()`` returns an EntityList that is EMPTY until ``.Load()`` is
    called — the single easiest mistake to make against this API, because
    iterating an unloaded list yields nothing and looks exactly like a company
    with no records.

    ``limit`` caps how many we materialise into Python, but note the caveat
    below: it does not cap what Sage loads.
    """
    if entity_list is None:
        return []
    try:
        entity_list.Load()
    except Exception as exc:
        logger.error("EntityList.Load() failed: %s", exc)
        raise

    out: List[Any] = []
    for item in entity_list:
        out.append(item)
        if limit is not None and len(out) >= limit:
            break
    return out


# ── phone numbers ────────────────────────────────────────────────────────────

def phone_at(phone_numbers, index: int = 0) -> str:
    """
    Read one number from a PhoneNumberCollection.

    Sage exposes phones as an indexed collection of PhoneNumber{Key, Number}
    rather than the Telephone1/Telephone2/Fax properties the old code assumed.
    """
    if phone_numbers is None:
        return ""
    try:
        if phone_numbers.Count <= index:
            return ""
        return text(phone_numbers[index].Number)
    except Exception:
        return ""


# ── addresses ────────────────────────────────────────────────────────────────

def address_dict(address) -> Dict[str, str]:
    """Flatten a Sage Address. Missing address -> all-empty dict, never None."""
    empty = {"address1": "", "address2": "", "city": "", "state": "",
             "zip": "", "country": ""}
    if address is None:
        return empty
    try:
        return {
            "address1": text(address.Address1),
            "address2": text(address.Address2),
            "city": text(address.City),
            "state": text(address.State),
            "zip": text(address.Zip),
            "country": text(address.Country),
        }
    except Exception:
        return empty


def contact_address(contact) -> Dict[str, str]:
    """Address from a Contact (Customer.BillToContact, Vendor.MailToContact)."""
    if contact is None:
        return address_dict(None)
    try:
        return address_dict(contact.Address)
    except Exception:
        return address_dict(None)
