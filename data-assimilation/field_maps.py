"""field_maps.py — Sage 50 2013 (Peachtree) → Synbot snapshot table field mappings.

Each entity map defines:
  sage_tables    : candidate Pervasive table names to try (first match wins)
  target_table   : Synbot PostgreSQL snapshot table name
  fields         : {synbot_column: [candidate_sage_columns...]}
                   first candidate found in the schema wins (case-insensitive)
  status_transform : optional callable(raw_value) → normalised string
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Status / value transformers
# ---------------------------------------------------------------------------

def _active_to_status(val: Any) -> str:
    if val is None:
        return "active"
    s = str(val).strip().upper()
    return "active" if s in ("Y", "YES", "1", "TRUE", "T", "ACTIVE", "A") else "inactive"


def _active_to_bool(val: Any) -> str:
    if val is None:
        return "true"
    s = str(val).strip().upper()
    return "true" if s in ("Y", "YES", "1", "TRUE", "T", "ACTIVE", "A") else "false"


def _invoice_status(val: Any) -> str:
    if val is None:
        return "unpaid"
    s = str(val).strip().upper()
    if s in ("P", "PAID", "CLOSED", "C"):
        return "paid"
    if s in ("PT", "PARTIAL", "T"):
        return "partial"
    return "unpaid"


def _to_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _to_float(val: Any) -> str:
    if val is None:
        return "0"
    try:
        return str(round(float(str(val).replace(",", "")), 4))
    except (ValueError, TypeError):
        return "0"


# ---------------------------------------------------------------------------
# Entity maps
# ---------------------------------------------------------------------------

ENTITY_MAPS: Dict[str, Dict] = {

    "customers": {
        "sage_tables": [
            "CUSTOMER", "AR_CUSTOMER", "CUSTOMERLIST", "CUSTLIST",
            "ARCU", "ARMASTER",
        ],
        "target_table": "sage_customers_snapshot",
        "fields": {
            "customer_id": ["CustId", "CustomerID", "ID", "CustKey", "CUSTNO",
                            "CustCode", "AcctNo"],
            "name":        ["Name", "CustomerName", "CompanyName", "FullName",
                            "CustName", "CUSTNAME"],
            "email":       ["EmailAddress", "Email", "EMail", "EmailAddr"],
            "phone":       ["Telephone1", "Phone", "PhoneNumber", "Tel",
                            "Phone1", "PHONE"],
            "status":      ["Active", "Status", "CustomerType", "CustStatus"],
        },
        "transforms": {
            "status": _active_to_status,
        },
    },

    "vendors": {
        "sage_tables": [
            "VENDOR", "AP_VENDOR", "VENDORLIST", "VNDLIST",
            "APVENDOR", "APMASTER", "APVN",
        ],
        "target_table": "sage_vendors_snapshot",
        "fields": {
            "vendor_id":       ["VendorID", "VendorId", "ID", "VendorKey",
                                "VendNo", "VendCode", "VENDNO"],
            "vendor_name":     ["Name", "VendorName", "CompanyName", "VENDNAME"],
            "contact_name":    ["Contact", "ContactName", "ContactPerson",
                                "VendContact"],
            "email":           ["EmailAddress", "Email", "EMail"],
            "phone":           ["Telephone1", "Phone", "PhoneNumber", "PHONE"],
            "address":         ["Address1", "Address", "Street", "Addr1"],
            "city":            ["City"],
            "state":           ["State", "Province"],
            "country":         ["Country"],
            "payment_terms":   ["PaymentTerms", "Terms", "PayTerms", "TERMS"],
            "tax_id":          ["TaxID", "VATNumber", "TaxNumber", "TAXID"],
            "current_balance": ["Balance", "CurrentBalance", "AmountDue",
                                "BALANCE"],
            "status":          ["Active", "Status", "VendStatus"],
        },
        "transforms": {
            "status":          _active_to_status,
            "current_balance": _to_float,
        },
    },

    "chart_of_accounts": {
        "sage_tables": [
            "ACCOUNT", "GL_ACCOUNT", "CHARTOFACCOUNTS", "GLACCT",
            "GLMASTER", "GLACCOUNT", "ACCTMASTER",
        ],
        "target_table": "sage_coa_snapshot",
        "fields": {
            "account_id":        ["AccountID", "AccountId", "ID", "AcctID",
                                  "ACCTID", "AcctNo"],
            "account_code":      ["AccountNumber", "AccountCode", "AcctNo",
                                  "AccountID", "ACCTNO"],
            "account_name":      ["Description", "AccountName", "AcctName",
                                  "Name", "ACCTDESC"],
            "account_type":      ["AccountType", "AcctType", "Type", "ACCTTYPE"],
            "parent_account_id": ["ParentAccountID", "ParentID", "ParentAcctID"],
            "description":       ["LongDescription", "Notes", "Memo"],
            "is_active":         ["Active", "IsActive", "Status"],
        },
        "transforms": {
            "is_active": _active_to_bool,
        },
    },

    "items": {
        "sage_tables": [
            "INVENTORYITEM", "IN_ITEM", "ITEMLIST", "ITEM", "STOCKITEM",
            "INVITEM", "INVMASTER", "INITEM",
        ],
        "target_table": "sage_items_snapshot",
        "fields": {
            "item_id":             ["ItemID", "StockCode", "ItemCode", "ID",
                                    "SKU", "ITEMID", "INVID"],
            "item_name":           ["Description", "ItemName", "Name",
                                    "StockDescription", "ITEMDESC"],
            "category":            ["ItemClassID", "Category", "ItemClass",
                                    "ClassID", "ITEMCLASS"],
            "unit":                ["UOM", "UnitOfMeasure", "Unit", "UOMCode"],
            "cost_price":          ["Cost", "CostPrice", "UnitCost",
                                    "AverageCost", "COST"],
            "selling_price":       ["UnitPrice", "SalesPrice", "Price",
                                    "SellingPrice", "PRICE"],
            "vat_category":        ["TaxType", "VATCode", "TaxCode",
                                    "SalesTaxType"],
            "reorder_level":       ["MinimumStock", "ReorderPoint",
                                    "ReorderLevel", "MINSTOCK"],
            "preferred_vendor_id": ["VendorID", "PrefVendor",
                                    "PreferredVendorID"],
            "expiry_date":         ["ExpiryDate", "ExpiryDt", "ExpDate", "Expiry"],
            "batch_number":        ["LotCode", "BatchNumber", "BatchCode",
                                    "LotNo", "BatchNo"],
            "is_active":           ["Active", "IsActive", "Status"],
        },
        "transforms": {
            "is_active":      _active_to_bool,
            "cost_price":     _to_float,
            "selling_price":  _to_float,
            "reorder_level":  _to_float,
        },
    },

    "stock_on_hand": {
        "sage_tables": [
            "INVENTORYITEM", "IN_ITEM", "ITEMLIST", "ITEM", "STOCKITEM",
            "INVITEM", "INVMASTER", "INITEM",
        ],
        "target_table": "sage_inventory_snapshot",
        "fields": {
            "item_id":          ["ItemID", "StockCode", "ItemCode", "ID",
                                 "SKU", "ITEMID"],
            "item_name":        ["Description", "ItemName", "Name",
                                 "StockDescription"],
            "quantity_on_hand": ["QuantityOnHand", "QtyOnHand", "Quantity",
                                 "StockQty", "QuantityAvailable", "QTYONHAND",
                                 "QtyAvail"],
            "unit_cost":        ["Cost", "UnitCost", "AverageCost",
                                 "CostPrice", "COST"],
            "total_value":      ["TotalValue", "StockValue", "InventoryValue",
                                 "STOCKVALUE"],
            "reorder_level":    ["MinimumStock", "ReorderPoint", "ReorderLevel"],
            "reorder_quantity": ["ReorderQuantity", "ReorderQty",
                                 "OrderQuantity"],
            "warehouse_id":     ["WarehouseID", "LocationID", "Location"],
        },
        "transforms": {
            "quantity_on_hand": _to_float,
            "unit_cost":        _to_float,
            "total_value":      _to_float,
        },
    },

    "sales_invoices": {
        "sage_tables": [
            "SALESINVOICE", "AR_INVOICE", "INVOICE", "ARINVOICE",
            "ARHEADER", "ARJRNL", "ARINV", "SOINVOICE",
        ],
        "target_table": "sage_ar_snapshot",
        "fields": {
            "invoice_id":   ["InvoiceNo", "InvoiceNumber", "InvoiceID", "ID",
                             "INVNO", "DocNo", "RefNo"],
            "customer_id":  ["CustomerID", "CustId", "CustKey", "CUSTNO"],
            "invoice_date": ["Date", "InvoiceDate", "TransactionDate",
                             "INVDATE", "DocDate"],
            "due_date":     ["DueDate", "DiscountDate", "PaymentDueDate",
                             "DUEDATE"],
            "net_amount":   ["AmountDue", "Amount", "NetAmount",
                             "TotalAmount", "InvoiceTotal", "AMOUNT",
                             "NETAMT", "INVAMT"],
            "status":       ["Status", "PaidStatus", "InvoiceStatus",
                             "PAYSTATUS"],
        },
        "transforms": {
            "status":     _invoice_status,
            "net_amount": _to_float,
        },
    },

    "sales_invoice_lines": {
        "sage_tables": [
            "SALESINVOICEITEM", "AR_INVOICEDETAIL", "INVOICEITEM",
            "SALESLINE", "INVOICELINE", "ARDETAIL", "ARLINEITEM",
            "SODETAIL", "ARROW",
        ],
        "target_table": "sage_invoice_lines_snapshot",
        "fields": {
            "line_id":      ["LineID", "LineNo", "ID", "DetailID",
                             "LINENO", "RowNo"],
            "invoice_id":   ["InvoiceNo", "InvoiceNumber", "InvoiceID",
                             "INVNO", "DocNo"],
            "item_id":      ["ItemID", "StockCode", "ItemCode", "ITEMID"],
            "quantity":     ["Quantity", "Qty", "SalesQty", "QTY"],
            "unit_price":   ["UnitPrice", "Price", "SalesPrice", "PRICE"],
            "discount":     ["Discount", "DiscountAmount", "DiscountPct"],
            "line_total":   ["Amount", "LineTotal", "ExtendedAmount",
                             "LineAmount", "AMOUNT"],
            "cost_at_sale": ["Cost", "UnitCost", "CostAtSale"],
        },
        "transforms": {
            "quantity":     _to_float,
            "unit_price":   _to_float,
            "discount":     _to_float,
            "line_total":   _to_float,
            "cost_at_sale": _to_float,
        },
    },

    "purchase_orders": {
        "sage_tables": [
            "PURCHASEORDER", "AP_PURCHASEORDER", "POHEADER", "PO",
            "APPO", "POMASTER",
        ],
        "target_table": "sage_purchase_orders_snapshot",
        "fields": {
            "po_id":                  ["PurchaseOrderNo", "POID", "PONumber",
                                       "ID", "PONO"],
            "po_number":              ["PurchaseOrderNo", "PONumber", "POID",
                                       "ID", "PONO"],
            "vendor_id":              ["VendorID", "VendorId", "VendorKey",
                                       "VENDNO"],
            "order_date":             ["Date", "OrderDate", "PODate",
                                       "PODATE"],
            "expected_delivery_date": ["ShipByDate", "DeliveryDate",
                                       "ExpectedDate", "RequiredDate",
                                       "SHIPDATE"],
            "total_amount":           ["Amount", "TotalAmount", "POTotal",
                                       "GrossAmount", "AMOUNT"],
            "tax_amount":             ["TaxAmount", "Tax", "VATAmount"],
            "net_amount":             ["NetAmount", "Amount", "TotalAmount",
                                       "NETAMT"],
            "status":                 ["Status", "POStatus", "OrderStatus"],
            "created_by":             ["CreatedBy", "EnteredBy", "UserID"],
        },
        "transforms": {
            "total_amount": _to_float,
            "tax_amount":   _to_float,
            "net_amount":   _to_float,
        },
    },

    "inventory_transactions": {
        "sage_tables": [
            "INVENTORYTRANSACTION", "IN_TRANSACTION", "INVTRANS",
            "STOCKTRANSACTION", "INTRANS", "IMTRANS",
        ],
        "target_table": "sage_inv_transactions_snapshot",
        "fields": {
            "transaction_id":   ["TransactionID", "ID", "TransID",
                                 "Reference", "TRANSID"],
            "item_id":          ["ItemID", "StockCode", "ItemCode"],
            "warehouse_id":     ["WarehouseID", "LocationID", "Location"],
            "transaction_type": ["TransType", "Type", "TransactionType",
                                 "TRANSTYPE"],
            "quantity_in":      ["QuantityIn", "QtyIn", "ReceiveQty",
                                 "QTYIN"],
            "quantity_out":     ["QuantityOut", "QtyOut", "IssueQty",
                                 "QTYOUT"],
            "unit_cost":        ["UnitCost", "Cost"],
            "reference_number": ["Reference", "ReferenceNo", "DocNo",
                                 "REFNO"],
            "transaction_date": ["Date", "TransDate", "TransactionDate",
                                 "TRANSDATE"],
            "posted_by":        ["PostedBy", "EnteredBy", "UserID"],
        },
        "transforms": {
            "quantity_in":  _to_float,
            "quantity_out": _to_float,
            "unit_cost":    _to_float,
        },
    },

    # Binary-scanner entity — populated from JrnlRow.DAT raw bytes (no ODBC).
    # Columns available: description, posting_date, record_id only.
    # Debit/credit amounts and GL account codes are not yet decoded.
    "jrnl_transactions": {
        "sage_tables": [],          # not used — data comes from btrieve_scanner
        "target_table": "sage_gl_snapshot",
        "fields": {
            "description":  ["description"],
            "posting_date": ["posting_date"],
            "account_id":   ["record_id"],  # best available surrogate for account_id
        },
        "transforms": {},
    },

    "gl_journal_entries": {
        "sage_tables": [
            "GENERICJOURNAL", "GL_JOURNALDETAIL", "GL_JOURNAL",
            "JOURNALENTRY", "JOURNAL", "JRNLROW", "JRNLHDR",
            "GLDETAIL", "GLJRNL",
        ],
        "target_table": "sage_gl_snapshot",
        "fields": {
            "account_id":    ["AccountID", "AccountNumber", "AcctNo",
                              "AccountCode", "ACCTNO"],
            "posting_date":  ["PostingDate", "Date", "TransactionDate",
                              "JournalDate", "POSTDATE"],
            "description":   ["Description", "Memo", "Reference",
                              "Narration", "MEMO"],
            "debit_amount":  ["Debit", "DebitAmount", "Dr", "DEBIT"],
            "credit_amount": ["Credit", "CreditAmount", "Cr", "CREDIT"],
        },
        "transforms": {
            "debit_amount":  _to_float,
            "credit_amount": _to_float,
        },
        "amount_split": True,  # if only "Amount" column exists, split by sign
        "amount_candidates": ["Amount", "JournalAmount", "Value",
                              "LineAmount", "AMOUNT"],
    },

    "staff": {
        "sage_tables": [
            "EMPLOYEE", "PR_EMPLOYEE", "HR_EMPLOYEE", "STAFF",
            "PREMPLOYEE", "HREMPLOYEE",
        ],
        "target_table": "sage_staff_snapshot",
        "fields": {
            "staff_id":   ["EmployeeID", "EmpID", "ID", "StaffID",
                           "EMPID", "EMPNO"],
            "full_name":  ["FullName", "Name", "EmployeeName", "EMPNAME"],
            "email":      ["EmailAddress", "Email", "EMAIL"],
            "department": ["Department", "Dept", "DepartmentID", "DEPT"],
            "role":       ["JobTitle", "Title", "Position", "Role",
                           "JOBTITLE"],
            "status":     ["Active", "Status", "EmpStatus"],
        },
        "transforms": {
            "status": _active_to_status,
        },
        # If FullName not found, construct from first + last
        "build_full_name": True,
        "first_name_candidates": ["FirstName", "First", "FIRSTNAME"],
        "last_name_candidates":  ["LastName", "Last", "Surname", "LASTNAME"],
    },

    "hr_payroll": {
        "sage_tables": [
            "PAYROLL", "PR_PAYROLL", "HRPAYROLL", "PAYTRANS",
            "PRMASTER",
        ],
        "target_table": "sage_payroll_snapshot",
        "fields": {
            "employee_id":    ["EmployeeID", "EmpID", "ID", "EMPID"],
            "department":     ["Department", "Dept", "DEPT"],
            "period":         ["Period", "PayPeriod", "PERIOD"],
            "salary":         ["Salary", "BaseSalary", "GrossSalary",
                               "SALARY"],
            "overtime_hours": ["OvertimeHours", "OTHours", "OTHOURS"],
            "overtime_rate":  ["OvertimeRate", "OTRate", "OTRATE"],
            "total_gross":    ["TotalGross", "GrossPay", "GROSSAMT"],
            "deductions":     ["Deductions", "TotalDeductions", "DEDUCTIONS"],
            "net_pay":        ["NetPay", "Net", "NETPAY"],
        },
        "transforms": {
            "salary":         _to_float,
            "overtime_hours": _to_float,
            "overtime_rate":  _to_float,
            "total_gross":    _to_float,
            "deductions":     _to_float,
            "net_pay":        _to_float,
        },
    },
}


# ---------------------------------------------------------------------------
# Target table lookup (for direct DB loader)
# ---------------------------------------------------------------------------

TARGET_TABLES: Dict[str, str] = {
    entity: cfg["target_table"]
    for entity, cfg in ENTITY_MAPS.items()
}


# ---------------------------------------------------------------------------
# Column resolver
# ---------------------------------------------------------------------------

def resolve_column(available_cols: List[str], candidates: List[str]) -> Optional[str]:
    """Return the first candidate column found in available_cols (case-insensitive)."""
    avail_lower = {c.lower(): c for c in available_cols}
    for candidate in candidates:
        match = avail_lower.get(candidate.lower())
        if match:
            return match
    return None


def map_row(
    raw_row: Dict[str, Any],
    entity_name: str,
    available_cols: List[str],
) -> Optional[Dict[str, str]]:
    """Map a raw Sage row to a Synbot snapshot row.

    Returns None if a required key field is missing (row will be skipped).
    """
    cfg = ENTITY_MAPS.get(entity_name)
    if not cfg:
        return None

    out: Dict[str, str] = {}
    transforms: Dict[str, Callable] = cfg.get("transforms", {})
    field_map: Dict[str, List[str]] = cfg["fields"]

    for synbot_col, candidates in field_map.items():
        src_col = resolve_column(available_cols, candidates)
        val = raw_row.get(src_col) if src_col else None

        transform = transforms.get(synbot_col)
        if transform:
            val = transform(val)
        elif val is None:
            val = ""
        else:
            val = _to_str(val)

        out[synbot_col] = val

    # Build full_name from first + last if missing
    if cfg.get("build_full_name") and not out.get("full_name"):
        first_col = resolve_column(available_cols, cfg.get("first_name_candidates", []))
        last_col  = resolve_column(available_cols, cfg.get("last_name_candidates", []))
        first = _to_str(raw_row.get(first_col)) if first_col else ""
        last  = _to_str(raw_row.get(last_col))  if last_col  else ""
        out["full_name"] = f"{first} {last}".strip() or out.get("staff_id", "")

    # Handle GL amount split (signed Amount → debit/credit)
    if cfg.get("amount_split"):
        if not out.get("debit_amount") and not out.get("credit_amount"):
            amount_candidates = cfg.get("amount_candidates", ["Amount"])
            amt_col = resolve_column(available_cols, amount_candidates)
            if amt_col:
                try:
                    amt = float(str(raw_row.get(amt_col) or 0).replace(",", ""))
                    out["debit_amount"]  = str(round(max(0.0, amt),  4))
                    out["credit_amount"] = str(round(max(0.0, -amt), 4))
                except (ValueError, TypeError):
                    pass

    # Require at least the primary ID column to be non-empty
    first_synbot_col = list(field_map.keys())[0]
    if not out.get(first_synbot_col):
        return None

    return out
