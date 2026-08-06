"""
verify_sdk_api.py — Assert every Sage API name sdk_client.py uses really exists.

WHY
---
The original sdk_client.py was written against an API that Sage.Peachtree.API
2013.0.0.826 does not have: ProductType, Company.SalesInvoices,
Company.Customers, invoice.TotalAmount, and about twenty more. None of it fails
at import. It fails at the first real call, gets caught by main.py's
degraded-start handler, and leaves the bridge running ODBC-only — every invoice
arriving without tax, every write path dead, and the service reporting itself
healthy.

This script makes that class of mistake impossible to ship. It reflects over
the real assembly and asserts that every type, property and method the bridge
calls actually exists. It needs the DLL but NOT a company file, so it runs on
any machine with Sage installed, in seconds, without touching data.

RUN IT
------
    python verify_sdk_api.py

    # or against a non-default install:
    python verify_sdk_api.py --dll "C:\\path\\to\\API\\Sage.Peachtree.API.dll"

Exit code 0 = every name checks out. Non-zero = the SDK on this machine differs
from what the bridge targets, and the failures name exactly which members are
missing.

Run this BEFORE verify_onsite.py. If it fails there is no point testing
anything else — the SDK path cannot work.
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

os.environ.setdefault("BRIDGE_API_KEY", "verify-only-key-not-used-for-auth-1234")

_parser = argparse.ArgumentParser(description="Verify the Sage SDK API surface")
_parser.add_argument("--dll", default="", help="path to Sage.Peachtree.API.dll")
_parser.add_argument("--install-dir", default="", help="Peachtree program folder")
_args = _parser.parse_args()

try:
    from config import get_settings
    _settings = get_settings()
    DLL = _args.dll or _settings.SAGE_API_DLL_PATH
    INSTALL_DIR = _args.install_dir or _settings.SAGE_INSTALL_DIR
except Exception:
    DLL = _args.dll
    INSTALL_DIR = _args.install_dir

if not DLL or not os.path.isfile(DLL):
    print("Sage.Peachtree.API.dll not found at: {!r}".format(DLL))
    print("Pass --dll, or set SAGE_API_DLL_PATH in .env")
    sys.exit(2)

import sdk_client  # noqa: E402

try:
    sdk_client.load_sdk(DLL, INSTALL_DIR)
except Exception as exc:
    print("Could not load the SDK: {}".format(exc))
    sys.exit(2)

import System  # noqa: E402
from System.Reflection import Assembly  # noqa: E402

asm = Assembly.LoadFrom(DLL)
by_name = {t.FullName: t for t in asm.GetTypes()}
fails = []
checks = 0


def has_member(type_full, member):
    """Name-based lookup: GetMethod() throws AmbiguousMatchException on overloads."""
    t = by_name.get(type_full)
    if t is None:
        return False, "type missing"
    for p in t.GetProperties():
        if p.Name == member:
            return True, "prop"
    for m in t.GetMethods():
        if m.Name == member:
            return True, "method"
    return False, "no such member"


def check(type_full, members):
    global checks
    for m in members:
        checks += 1
        ok, why = has_member(type_full, m)
        if not ok:
            fails.append("%s.%s (%s)" % (type_full.split(".")[-1], m, why))


P = "Sage.Peachtree.API."

check(P + "PeachtreeSession", [
    "Begin", "End", "Dispose", "Open", "Close", "CompanyList",
    "VerifyAccess", "RequestAccess", "SessionActive",
])
check(P + "Company", ["Factories", "IsClosed", "CompanyIdentifier"])
check(P + "CompanyIdentifier",
      ["CompanyName", "Path", "DatabaseName", "ServerName", "SchemaVersion", "Guid"])
check(P + "EntityReference", ["Guid", "IsEmpty", "Load"])

check(P + "SalesInvoice", [
    "Amount", "AmountDue", "Date", "DateDue", "CustomerReference",
    "ReferenceNumber", "CustomerPurchaseOrderNumber", "SalesTaxAmount",
    "SalesTaxCodeReference", "FreightAmount", "DiscountAmount", "ShipVia",
    "CustomerNote", "InternalNote", "TermsDescription", "IsPosted", "Key",
    "ApplyToSalesLines", "AddSalesLine", "Save", "Delete", "IsDeleteAllowed",
    "Validate",
])
check(P + "SalesInvoiceSalesLine", [
    "Description", "Quantity", "UnitPrice", "Amount", "AccountReference",
    "InventoryItemReference", "SalesTaxType",
])
check(P + "Customer", [
    "ID", "Name", "Email", "Balance", "IsInactive", "BillToContact", "Terms",
    "PhoneNumbers", "AccountNumber", "Category", "LastInvoiceDate",
    "LastPaymentDate", "Save",
])
check(P + "PaymentTerms", ["CreditLimit"])
check(P + "Contact", ["Address", "Name", "Email", "PhoneNumbers"])
check(P + "Address", ["Address1", "Address2", "City", "State", "Zip", "Country"])
check(P + "PhoneNumber", ["Number"])
check(P + "Vendor", [
    "ID", "Name", "Email", "Balance", "IsInactive", "MailToContact",
    "PhoneNumbers", "TaxIDNumber", "Save",
])
check(P + "Account", ["ID", "Description", "Classification", "GetEndingBalance",
                      "IsInactive"])
check(P + "StockItem", [
    "ID", "Description", "ReorderQuantity", "MinimumStock", "QuantityOnHand",
    "PriceLevels", "SalesAccountReference", "COGSAccountReference",
    "InventoryAccountReference", "IsInactive", "IsTaxable", "Weight",
    "PartNumber", "UPC", "Location", "Category",
])
check(P + "PriceLevel", ["UnitPrice"])
check(P + "Employee", ["ID", "Name", "Email", "PhoneNumbers", "IsInactive",
                       "IsSalesRepresentative"])
check(P + "Receipt", [
    "Amount", "Date", "CustomerReference", "ReferenceNumber", "ReceiptNumber",
    "DepositTicketID", "PaymentMethod", "AddInvoiceLine", "AddSalesLine", "Save",
])
check(P + "ReceiptInvoiceLine", ["AmountPaid"])
check(P + "PurchaseInvoice", ["Amount", "AmountDue", "Date", "DateDue",
                              "VendorReference", "ReferenceNumber", "IsPosted"])
check(P + "SalesOrder", [
    "Amount", "Date", "ShipByDate", "CustomerReference", "ReferenceNumber",
    "CustomerPurchaseOrderNumber", "SalesOrderLines", "AddLine", "Save",
    "IsClosed",
])
check(P + "PurchaseOrder", [
    "Amount", "Date", "GoodThroughDate", "VendorReference", "ReferenceNumber",
    "PurchaseOrderLines", "AddLine", "Save", "IsClosed",
])
check(P + "GeneralJournalEntry", [
    "Date", "ReferenceNumber", "GeneralJournalEntryLines", "AddLine", "Save",
    "IsPosted",
])
check(P + "GeneralJournalEntryLine", ["AccountReference", "Amount", "Description"])
check(P + "Quote", ["Amount", "Date", "GoodThroughDate", "CustomerReference",
                    "ReferenceNumber"])
check(P + "Job", ["ID", "Description", "IsInactive"])

# Factories referenced by _factory(company, "...")
comp = by_name[P + "Company"]
fac_type = comp.GetProperty("Factories").PropertyType
fac_names = {p.Name for p in fac_type.GetProperties()}
for name in ["CustomerFactory", "VendorFactory", "SalesInvoiceFactory",
             "SalesOrderFactory", "PurchaseOrderFactory", "InventoryItemFactory",
             "AccountFactory", "EmployeeFactory", "ReceiptFactory",
             "PurchaseInvoiceFactory", "GeneralJournalEntryFactory",
             "QuoteFactory", "JobFactory"]:
    checks += 1
    if name not in fac_names:
        fails.append("Company.Factories.%s missing" % name)

# AuthorizationResult members used by _authorization_help
ar = by_name[P + "AuthorizationResult"]
ar_names = set(System.Enum.GetNames(ar))
for name in ["Granted", "Pending", "Denied", "CompanyLocked", "LoginRestricted",
             "NoCredentials", "CorruptedOrTampered", "None"]:
    checks += 1
    if name not in ar_names:
        fails.append("AuthorizationResult.%s missing" % name)

# ValidationProblemList used by _save_entity. Note it lives in the ROOT
# namespace, not in .Validations where the concrete problem subclasses are.
checks += 1
if by_name.get("Sage.Peachtree.API.ValidationProblemList") is None:
    fails.append("ValidationProblemList missing")

print("=" * 68)
print(" Sage SDK API verification")
print("=" * 68)
print("assembly : %s" % asm.FullName)
print("checked  : %d API names" % checks)
print()

if fails:
    print("FAILED — %d name(s) the bridge uses are NOT in this assembly:" % len(fails))
    for f in fails:
        print("   * " + f)
    print()
    print("The SDK on this machine differs from the 2013.0.0.826 build the")
    print("bridge targets. sdk_client.py must be reconciled against it before")
    print("the SDK path can work. Until then the bridge runs ODBC-only and")
    print("invoices sync with completeness=partial.")
    sys.exit(1)

print("OK — every type, property and method the bridge calls exists here.")
print()
print("This proves the API surface only. It does NOT prove the values are")
print("correct; that needs a real company file. Run verify_onsite.py next.")
sys.exit(0)
