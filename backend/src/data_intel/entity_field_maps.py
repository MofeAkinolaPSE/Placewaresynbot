"""entity_field_maps.py — backend-local mirror of Sage 50 → ACE field mappings.

**Why this file exists (read before editing):** this app has TWO independently
maintained Sage-field-mapping registries today:

  1. `data-assimilation/field_maps.py` (`ENTITY_MAPS`) — candidate *DAT* column
     lists, used only by the one-time historical Sage-binary migration.
  2. `backend/src/routers/sage_csv_import.py`'s `_map_*` functions — hand-coded
     *CSV header* mappings, used by the live, ongoing `POST /sage/import/csv`
     path that actually populates the DB day to day.

There is no single source of truth between them, and the backend process
cannot import `data-assimilation/field_maps.py` live (it's a separate
deployment unit — see `backend/Dockerfile`, which never copies
`data-assimilation/` into the `chat-backend.v1` image). Rather than invent a
fourth mapping registry, this file is an **explicitly-labelled, hand-maintained
mirror** of registry #1 (`DAT_ENTITY_MAPS`, candidate columns transcribed
verbatim for display) plus a transcription of registry #2's CSV-native
entities (`CSV_NATIVE_ENTITY_MAPS`, entities `field_maps.py` doesn't know
about at all: gl_detail, cash_register, gl_account_summary, customer_sales).

This is transcription, not automation — if either upstream file changes its
column candidates, this file must be updated by hand. See
data-assimilation/docs.md/ACE-Data-Intelligence-Layer.md Chapter 1 for the
documented future-phase fix (a shared `ace_mappings` package).

`REQUIRED_FIELDS` doubles as the input to the Commercial Data Explorer's
quality badge rule (see explorer_service.py) — a missing required field on a
record is a 🔴, not a vibe.
"""
from __future__ import annotations

from typing import Dict, List


# ---------------------------------------------------------------------------
# DAT-translated entities — mirrors data-assimilation/field_maps.py ENTITY_MAPS
# ---------------------------------------------------------------------------

DAT_ENTITY_MAPS: Dict[str, Dict] = {

    "customers": {
        "target_table": "sage_customers_snapshot",
        "silver_view": "v_customers",
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
    },

    "vendors": {
        "target_table": "sage_vendors_snapshot",
        "silver_view": "v_vendors",
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
            "current_balance": ["Balance", "CurrentBalance", "AmountDue", "BALANCE"],
            "status":          ["Active", "Status", "VendStatus"],
        },
    },

    "chart_of_accounts": {
        "target_table": "sage_coa_snapshot",
        "silver_view": "v_chart_of_accounts",
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
    },

    "items": {
        "target_table": "sage_items_snapshot",
        "silver_view": "v_inventory",
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
            "vat_category":        ["TaxType", "VATCode", "TaxCode", "SalesTaxType"],
            "reorder_level":       ["MinimumStock", "ReorderPoint",
                                     "ReorderLevel", "MINSTOCK"],
            "preferred_vendor_id": ["VendorID", "PrefVendor", "PreferredVendorID"],
            "expiry_date":         ["ExpiryDate", "ExpiryDt", "ExpDate", "Expiry"],
            "batch_number":        ["LotCode", "BatchNumber", "BatchCode",
                                     "LotNo", "BatchNo"],
            "is_active":           ["Active", "IsActive", "Status"],
        },
    },

    "stock_on_hand": {
        "target_table": "sage_inventory_snapshot",
        "silver_view": None,
        "fields": {
            "item_id":          ["ItemID", "StockCode", "ItemCode", "ID", "SKU", "ITEMID"],
            "item_name":        ["Description", "ItemName", "Name", "StockDescription"],
            "quantity_on_hand": ["QuantityOnHand", "QtyOnHand", "Quantity",
                                 "StockQty", "QuantityAvailable", "QTYONHAND", "QtyAvail"],
            "unit_cost":        ["Cost", "UnitCost", "AverageCost", "CostPrice", "COST"],
            "total_value":      ["TotalValue", "StockValue", "InventoryValue", "STOCKVALUE"],
            "reorder_level":    ["MinimumStock", "ReorderPoint", "ReorderLevel"],
            "reorder_quantity": ["ReorderQuantity", "ReorderQty", "OrderQuantity"],
            "warehouse_id":     ["WarehouseID", "LocationID", "Location"],
        },
    },

    "sales_invoices": {
        "target_table": "sage_ar_snapshot",
        "silver_view": "v_ar_invoices",
        "fields": {
            "invoice_id":   ["InvoiceNo", "InvoiceNumber", "InvoiceID", "ID",
                              "INVNO", "DocNo", "RefNo"],
            "customer_id":  ["CustomerID", "CustId", "CustKey", "CUSTNO"],
            "invoice_date": ["Date", "InvoiceDate", "TransactionDate", "INVDATE", "DocDate"],
            "due_date":     ["DueDate", "DiscountDate", "PaymentDueDate", "DUEDATE"],
            "net_amount":   ["AmountDue", "Amount", "NetAmount", "TotalAmount",
                              "InvoiceTotal", "AMOUNT", "NETAMT", "INVAMT"],
            "status":       ["Status", "PaidStatus", "InvoiceStatus", "PAYSTATUS"],
        },
    },

    "sales_invoice_lines": {
        "target_table": "sage_invoice_lines_snapshot",
        "silver_view": "v_ar_invoice_lines",
        "fields": {
            "line_id":      ["LineID", "LineNo", "ID", "DetailID", "LINENO", "RowNo"],
            "invoice_id":   ["InvoiceNo", "InvoiceNumber", "InvoiceID", "INVNO", "DocNo"],
            "item_id":      ["ItemID", "StockCode", "ItemCode", "ITEMID"],
            "quantity":     ["Quantity", "Qty", "SalesQty", "QTY"],
            "unit_price":   ["UnitPrice", "Price", "SalesPrice", "PRICE"],
            "discount":     ["Discount", "DiscountAmount", "DiscountPct"],
            "line_total":   ["Amount", "LineTotal", "ExtendedAmount", "LineAmount", "AMOUNT"],
            "cost_at_sale": ["Cost", "UnitCost", "CostAtSale"],
        },
    },

    "purchase_orders": {
        "target_table": "sage_purchase_orders_snapshot",
        "silver_view": None,
        "fields": {
            "po_id":                  ["PurchaseOrderNo", "POID", "PONumber", "ID", "PONO"],
            "po_number":              ["PurchaseOrderNo", "PONumber", "POID", "ID", "PONO"],
            "vendor_id":              ["VendorID", "VendorId", "VendorKey", "VENDNO"],
            "order_date":             ["Date", "OrderDate", "PODate", "PODATE"],
            "expected_delivery_date": ["ShipByDate", "DeliveryDate", "ExpectedDate",
                                        "RequiredDate", "SHIPDATE"],
            "total_amount":           ["Amount", "TotalAmount", "POTotal",
                                        "GrossAmount", "AMOUNT"],
            "tax_amount":             ["TaxAmount", "Tax", "VATAmount"],
            "net_amount":             ["NetAmount", "Amount", "TotalAmount", "NETAMT"],
            "status":                 ["Status", "POStatus", "OrderStatus"],
            "created_by":             ["CreatedBy", "EnteredBy", "UserID"],
        },
    },

    "inventory_transactions": {
        "target_table": "sage_inv_transactions_snapshot",
        "silver_view": None,
        "fields": {
            "transaction_id":   ["TransactionID", "ID", "TransID", "Reference", "TRANSID"],
            "item_id":          ["ItemID", "StockCode", "ItemCode"],
            "warehouse_id":     ["WarehouseID", "LocationID", "Location"],
            "transaction_type": ["TransType", "Type", "TransactionType", "TRANSTYPE"],
            "quantity_in":      ["QuantityIn", "QtyIn", "ReceiveQty", "QTYIN"],
            "quantity_out":     ["QuantityOut", "QtyOut", "IssueQty", "QTYOUT"],
            "unit_cost":        ["UnitCost", "Cost"],
            "reference_number": ["Reference", "ReferenceNo", "DocNo", "REFNO"],
            "transaction_date": ["Date", "TransDate", "TransactionDate", "TRANSDATE"],
            "posted_by":        ["PostedBy", "EnteredBy", "UserID"],
        },
    },

    "gl_journal_entries": {
        "target_table": "sage_gl_snapshot",
        "silver_view": None,
        "fields": {
            "account_id":    ["AccountID", "AccountNumber", "AcctNo", "AccountCode", "ACCTNO"],
            "posting_date":  ["PostingDate", "Date", "TransactionDate",
                               "JournalDate", "POSTDATE"],
            "description":   ["Description", "Memo", "Reference", "Narration", "MEMO"],
            "debit_amount":  ["Debit", "DebitAmount", "Dr", "DEBIT"],
            "credit_amount": ["Credit", "CreditAmount", "Cr", "CREDIT"],
        },
    },

    "jrnl_transactions": {
        # Mirrors field_maps.py's own entry verbatim (target_table shared with
        # gl_journal_entries above — both write into sage_gl_snapshot).
        # This is the binary-scanner path (btrieve_scanner.py reading
        # JrnlRow.DAT raw bytes directly, sage_tables=[] means no DAT-table
        # candidate resolution happens for it), distinct from the separate,
        # later Btrieve LVAR streaming extraction that loaded 71,744 rows
        # into a DIFFERENT table, sage_gl_transactions (see load_gl_transactions.py
        # — columns post_date/gl_account/description, not tracked in this
        # registry since it isn't part of field_maps.ENTITY_MAPS).
        "target_table": "sage_gl_snapshot",
        "silver_view": None,
        "source_note": "Btrieve binary scan of JrnlRow.DAT — record_id used as account_id surrogate; see NON_EXTRACTABLE_FIELDS for amount extraction limits.",
        "fields": {
            "description":  ["description"],
            "posting_date": ["posting_date"],
            "account_id":   ["record_id"],
        },
    },

    "staff": {
        "target_table": "sage_staff_snapshot",
        "silver_view": None,
        "fields": {
            "staff_id":   ["EmployeeID", "EmpID", "ID", "StaffID", "EMPID", "EMPNO"],
            "full_name":  ["FullName", "Name", "EmployeeName", "EMPNAME"],
            "email":      ["EmailAddress", "Email", "EMAIL"],
            "department": ["Department", "Dept", "DepartmentID", "DEPT"],
            "role":       ["JobTitle", "Title", "Position", "Role", "JOBTITLE"],
            "status":     ["Active", "Status", "EmpStatus"],
        },
    },

    "hr_payroll": {
        "target_table": "sage_payroll_snapshot",
        "silver_view": None,
        "fields": {
            "employee_id":    ["EmployeeID", "EmpID", "ID", "EMPID"],
            "department":     ["Department", "Dept", "DEPT"],
            "period":         ["Period", "PayPeriod", "PERIOD"],
            "salary":         ["Salary", "BaseSalary", "GrossSalary", "SALARY"],
            "overtime_hours": ["OvertimeHours", "OTHours", "OTHOURS"],
            "overtime_rate":  ["OvertimeRate", "OTRate", "OTRATE"],
            "total_gross":    ["TotalGross", "GrossPay", "GROSSAMT"],
            "deductions":     ["Deductions", "TotalDeductions", "DEDUCTIONS"],
            "net_pay":        ["NetPay", "Net", "NETPAY"],
        },
    },
}


# ---------------------------------------------------------------------------
# CSV-native entities — near-1:1 passthrough, live import path only.
# Transcribed from backend/src/routers/sage_csv_import.py's _map_* functions.
# Rendered as a SEPARATE report section (see lineage_service.py) — showing
# "account_code -> account_code = 100%" next to genuinely-translated DAT
# columns would misleadingly pad the coverage numbers.
# ---------------------------------------------------------------------------

CSV_NATIVE_ENTITY_MAPS: Dict[str, Dict] = {

    "gl_detail": {
        "target_table": "sage_gl_detail_snapshot",
        "silver_view": None,
        "fields": {
            "account_code":    ["account_code", "account_id"],
            "account_name":    ["account_name"],
            "txn_date":        ["txn_date", "date"],
            "reference":       ["reference"],
            "journal_type":    ["journal_type"],
            "description":     ["description"],
            "debit":           ["debit"],
            "credit":          ["credit"],
            "running_balance": ["running_balance"],
            "source_file":     ["source_file"],
        },
    },

    "cash_register": {
        "target_table": "sage_cash_register_snapshot",
        "silver_view": None,
        "fields": {
            "txn_date":        ["txn_date", "date"],
            "trans_no":        ["trans_no"],
            "txn_type":        ["txn_type"],
            "description":     ["description"],
            "reference":       ["reference"],
            "payment_amount":  ["payment_amount"],
            "receipt_amount":  ["receipt_amount"],
            "running_balance": ["running_balance"],
            "source_file":     ["source_file"],
        },
    },

    "gl_account_summary": {
        "target_table": "sage_gl_account_summary_snapshot",
        "silver_view": None,
        "fields": {
            "account_code":      ["account_code", "account_number"],
            "account_name":      ["account_name"],
            "beginning_balance": ["beginning_balance"],
            "debit_change":      ["debit_change"],
            "credit_change":     ["credit_change"],
            "net_change":        ["net_change"],
            "ending_balance":    ["ending_balance"],
        },
    },

    "customer_sales": {
        "target_table": "sage_customer_sales_snapshot",
        "silver_view": None,
        "fields": {
            "customer_id":   ["customer_id"],
            "name":          ["name"],
            "amount":        ["amount"],
            "cost_of_sales": ["cost_of_sales"],
            "gross_profit":  ["gross_profit"],
            "gross_margin":  ["gross_margin"],
        },
    },
}


# ---------------------------------------------------------------------------
# Required fields — reuses field_maps.map_row()'s "first key is required"
# convention, plus a couple of obviously-required additions. Drives the
# Commercial Data Explorer's quality badge (see explorer_service.py).
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: Dict[str, List[str]] = {
    "customers":             ["customer_id", "name"],
    "vendors":                ["vendor_id", "vendor_name"],
    "chart_of_accounts":      ["account_id", "account_code"],
    "items":                  ["item_id", "item_name"],
    "stock_on_hand":          ["item_id"],
    "sales_invoices":         ["invoice_id", "customer_id", "net_amount"],
    "sales_invoice_lines":    ["line_id", "invoice_id"],
    "purchase_orders":        ["po_id", "vendor_id"],
    "inventory_transactions": ["transaction_id", "item_id"],
    "gl_journal_entries":     ["account_id"],
    "jrnl_transactions":      ["account_id"],
    "staff":                  ["staff_id"],
    "hr_payroll":             ["employee_id"],
    "gl_detail":              ["account_code"],
    "cash_register":          ["trans_no"],
    "gl_account_summary":     ["account_code"],
    "customer_sales":         ["customer_id"],
}


def all_entities() -> Dict[str, Dict]:
    """Combined DAT + CSV-native registry, entity name -> config."""
    combined: Dict[str, Dict] = {}
    combined.update(DAT_ENTITY_MAPS)
    combined.update(CSV_NATIVE_ENTITY_MAPS)
    return combined
