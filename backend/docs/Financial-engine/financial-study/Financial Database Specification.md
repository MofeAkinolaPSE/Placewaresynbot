# Synbot Financial Database Specification — V1

## 1. Database Design Objective

The Synbot Financial Database is the persistent foundation for the Financial Operating System.

It must support:

* multi-company operation;
* transactional accounting;
* double-entry bookkeeping;
* AR/AP;
* inventory and batch tracking;
* banking;
* fixed assets;
* payroll;
* budgeting;
* tax;
* approvals;
* audit;
* reporting;
* AI financial intelligence.

The database must enforce the principle:

> **Operational transactions are the source events; the General Ledger is the authoritative financial representation of those events.**

The database must not allow different modules to maintain competing versions of financial truth.

---

# 2. Database Technology

## Primary Database

**PostgreSQL**

Recommended because the system requires:

* strong relational integrity;
* transactions;
* foreign keys;
* check constraints;
* row-level security potential;
* JSONB for controlled flexible configuration;
* indexing;
* reporting queries;
* concurrency;
* reliable financial transactions.

The database should be treated as a **transactional financial database**, not merely an application data store.

---

# 3. Global Database Conventions

Every table should follow consistent conventions.

### Primary key

Use:

```text
id UUID
```

for internal identity.

### Business reference

Use a separate human-readable reference:

```text
invoice_number
payment_number
journal_number
purchase_order_number
```

etc.

### Common metadata

Transactional tables should generally support:

```text
created_at
created_by
updated_at
updated_by
```

Where appropriate:

```text
deleted_at
```

should **not** be used to silently remove posted financial records.

---

# 4. Multi-Company Foundation

The following entities form the organizational hierarchy:

```text
organization
    │
    └── legal_entity
            │
            ├── branch
            ├── department
            └── cost_centre
```

## `organizations`

```text
id
name
code
status
base_currency_id
created_at
updated_at
```

---

## `legal_entities`

```text
id
organization_id
name
code
registration_number
tax_identifier
base_currency_id
fiscal_year_start
status
created_at
updated_at
```

Every financial transaction should ultimately belong to a legal entity.

---

## `branches`

```text
id
legal_entity_id
name
code
address
status
```

---

## `departments`

```text
id
legal_entity_id
name
code
status
```

---

## `cost_centres`

```text
id
legal_entity_id
name
code
department_id
status
```

---

# 5. Currency

## `currencies`

```text
id
code
name
symbol
decimal_places
is_active
```

Example:

```text
NGN
USD
GBP
EUR
```

Do not hard-code currency behaviour into individual transaction modules.

---

# 6. Financial Periods

## `financial_periods`

```text
id
legal_entity_id
fiscal_year
period_number
name
start_date
end_date
status
closed_at
closed_by
```

Status:

```text
OPEN
CLOSED
```

Potential future state:

```text
LOCKED
```

A journal cannot be posted into a closed period.

---

# 7. Chart of Accounts

The COA is a fundamental master-data structure.

## `account_groups`

```text
id
legal_entity_id
parent_id
code
name
account_type
reporting_category
sort_order
status
```

Account types:

```text
ASSET
LIABILITY
EQUITY
REVENUE
EXPENSE
```

---

## `accounts`

```text
id
legal_entity_id
account_group_id
parent_account_id
code
name
account_type
normal_balance
is_control_account
is_postable
currency_id
status
```

`is_postable` determines whether transactions can be posted directly to the account.

For example:

```text
Assets
 ├── Current Assets       ← non-postable
 │    ├── Cash            ← postable
 │    ├── Bank            ← postable
 │    └── Receivables     ← postable
```

---

# 8. Customers

## `customers`

```text
id
legal_entity_id
customer_code
name
customer_type
tax_identifier
currency_id
payment_terms_id
credit_limit
receivable_account_id
status
created_at
updated_at
```

---

## `customer_contacts`

```text
id
customer_id
name
email
phone
role
is_primary
```

---

## `payment_terms`

```text
id
legal_entity_id
name
days
description
status
```

---

# 9. Suppliers

## `suppliers`

```text
id
legal_entity_id
supplier_code
name
supplier_type
tax_identifier
currency_id
payment_terms_id
payable_account_id
status
```

---

## `supplier_contacts`

```text
id
supplier_id
name
email
phone
role
is_primary
```

---

# 10. Products

## `product_categories`

```text
id
legal_entity_id
parent_id
name
code
status
```

---

## `units_of_measure`

```text
id
legal_entity_id
name
code
conversion_factor
status
```

---

## `products`

```text
id
legal_entity_id
category_id
sku
name
description
product_type
unit_of_measure_id
inventory_account_id
cogs_account_id
revenue_account_id
status
```

Product types may include:

```text
INVENTORY
SERVICE
NON_INVENTORY
```

---

# 11. Warehouses

## `warehouses`

```text
id
legal_entity_id
branch_id
name
code
address
status
```

---

## `warehouse_locations`

```text
id
warehouse_id
name
code
status
```

---

# 12. Product Batches

## `batches`

```text
id
product_id
batch_number
manufacturing_date
expiry_date
unit_cost
status
```

Status:

```text
AVAILABLE
QUARANTINED
DAMAGED
EXPIRED
RECALLED
LOANED
```

Batch numbers should be uniquely constrained within the appropriate legal-entity/product context.

---

# 13. Inventory Ledger

This is one of the most important tables in the system.

## `inventory_transactions`

```text
id
legal_entity_id
product_id
batch_id
warehouse_id
location_id
transaction_type
quantity
unit_cost
total_cost
transaction_date
source_type
source_id
reference
reason
status
created_by
created_at
```

Transaction types:

```text
PURCHASE
SALE
RETURN_IN
RETURN_OUT
TRANSFER_IN
TRANSFER_OUT
ADJUSTMENT
DAMAGE
EXPIRY
RECALL
LOAN_OUT
LOAN_RETURN
STOCK_COUNT
BATCH_REPLACEMENT
OPENING_BALANCE
```

Every stock movement should produce an inventory transaction.

---

# 14. Inventory Balance

## `inventory_balances`

This table is an operational read model.

```text
id
legal_entity_id
product_id
batch_id
warehouse_id
location_id
quantity
average_cost
last_updated_at
```

Important:

> `inventory_balances` must never become the only source of inventory truth.

The authoritative history is `inventory_transactions`.

The balance can be rebuilt from movements if required.

---

# 15. Sales

## `sales_orders`

```text
id
legal_entity_id
customer_id
branch_id
order_number
order_date
status
currency_id
subtotal
discount_amount
tax_amount
charge_amount
total_amount
```

---

## `sales_order_lines`

```text
id
sales_order_id
product_id
description
quantity
unit_price
discount_amount
tax_amount
line_total
```

---

# 16. Deliveries

## `deliveries`

```text
id
legal_entity_id
customer_id
sales_order_id
delivery_number
delivery_date
warehouse_id
status
```

---

## `delivery_lines`

```text
id
delivery_id
product_id
batch_id
quantity
unit_cost
```

---

# 17. Sales Invoices

## `sales_invoices`

```text
id
legal_entity_id
customer_id
sales_order_id
delivery_id
invoice_number
invoice_date
due_date
currency_id
exchange_rate
subtotal
discount_amount
tax_amount
charge_amount
total_amount
balance_due
status
```

Status may include:

```text
DRAFT
APPROVED
POSTED
PARTIALLY_PAID
PAID
VOIDED
```

---

## `sales_invoice_lines`

```text
id
invoice_id
product_id
description
quantity
unit_price
discount_amount
tax_amount
line_total
revenue_account_id
```

Batch information belongs to the inventory/delivery relationship rather than being unnecessarily duplicated on every invoice line.

---

# 18. Customer Payments

## `customer_payments`

```text
id
legal_entity_id
customer_id
payment_number
payment_date
payment_method
bank_account_id
cash_account_id
currency_id
amount
reference
status
```

---

## `payment_allocations`

```text
id
payment_id
invoice_id
allocated_amount
```

This allows:

```text
One payment → many invoices
One invoice → many payments
```

---

# 19. Credit Notes

## `credit_notes`

```text
id
legal_entity_id
customer_id
original_invoice_id
credit_note_number
date
reason
currency_id
total_amount
status
```

---

## `credit_note_lines`

```text
id
credit_note_id
product_id
description
quantity
amount
tax_amount
```

A credit note should generate the appropriate accounting event rather than directly editing the original invoice.

---

# 20. Procurement

## `purchase_requests`

```text
id
legal_entity_id
request_number
requested_by
department_id
required_date
status
```

---

## `purchase_orders`

```text
id
legal_entity_id
supplier_id
purchase_order_number
order_date
expected_date
currency_id
subtotal
tax_amount
total_amount
status
```

---

## `purchase_order_lines`

```text
id
purchase_order_id
product_id
description
quantity
unit_cost
tax_amount
line_total
```

---

# 21. Goods Receipts

## `goods_receipts`

```text
id
legal_entity_id
supplier_id
purchase_order_id
receipt_number
warehouse_id
receipt_date
status
```

---

## `goods_receipt_lines`

```text
id
goods_receipt_id
product_id
batch_id
quantity
unit_cost
accepted_quantity
rejected_quantity
```

This is where inventory can be introduced into the system.

---

# 22. Supplier Invoices

## `supplier_invoices`

```text
id
legal_entity_id
supplier_id
purchase_order_id
goods_receipt_id
invoice_number
supplier_invoice_number
invoice_date
due_date
currency_id
subtotal
tax_amount
total_amount
balance_due
status
```

A unique constraint should be considered around:

```text
supplier_id + supplier_invoice_number
```

to support duplicate-invoice detection.

---

# 23. Supplier Payments

## `supplier_payments`

```text
id
legal_entity_id
supplier_id
payment_number
payment_date
bank_account_id
cash_account_id
amount
currency_id
reference
status
```

---

# 24. Supplier Returns

## `supplier_returns`

```text
id
legal_entity_id
supplier_id
purchase_order_id
return_number
return_date
reason
status
```

## `supplier_return_lines`

```text
id
supplier_return_id
product_id
batch_id
quantity
unit_cost
```

The return should generate:

```text
Inventory decrease
+
AP adjustment
+
Accounting event
```

---

# 25. Expenses

## `expenses`

```text
id
legal_entity_id
expense_number
expense_date
employee_id
supplier_id
department_id
cost_centre_id
expense_account_id
amount
tax_amount
payment_method
status
description
```

The model should allow either:

```text
Employee expense
```

or:

```text
Supplier/vendor expense
```

depending on the workflow.

---

# 26. Bank Accounts

## `bank_accounts`

```text
id
legal_entity_id
bank_name
account_name
account_number
currency_id
gl_account_id
status
```

The actual bank account number should receive appropriate security treatment.

---

# 27. Cash Accounts

## `cash_accounts`

```text
id
legal_entity_id
name
code
currency_id
gl_account_id
branch_id
status
```

---

# 28. Bank Transactions

## `bank_transactions`

```text
id
bank_account_id
transaction_date
value_date
transaction_type
amount
reference
description
source_type
source_id
status
```

---

# 29. Bank Statements

## `bank_statements`

```text
id
bank_account_id
statement_number
start_date
end_date
opening_balance
closing_balance
status
```

---

## `bank_statement_transactions`

```text
id
bank_statement_id
transaction_date
value_date
description
reference
amount
transaction_type
```

---

# 30. Reconciliation

## `bank_reconciliations`

```text
id
bank_account_id
statement_id
reconciliation_date
book_balance
bank_balance
difference
status
completed_by
completed_at
```

---

## `reconciliation_items`

```text
id
reconciliation_id
statement_transaction_id
bank_transaction_id
match_type
status
```

Match types:

```text
EXACT
LIKELY
MANUAL
```

---

# 31. Accounting Events

## `accounting_events`

This is the bridge between modules and accounting.

```text
id
legal_entity_id
event_type
source_module
source_type
source_id
event_date
financial_period_id
currency_id
amount
status
created_at
```

Examples:

```text
SALES_INVOICE_POSTED
CUSTOMER_PAYMENT_RECEIVED
PURCHASE_INVOICE_POSTED
SUPPLIER_PAYMENT_POSTED
INVENTORY_ADJUSTED
PAYROLL_POSTED
DEPRECIATION_POSTED
BANK_CHARGE_POSTED
EXPENSE_POSTED
```

---

# 32. Journal Entries

## `journal_entries`

```text
id
legal_entity_id
journal_number
journal_date
financial_period_id
source_type
source_id
description
currency_id
status
reversal_of_id
posted_at
posted_by
```

Status:

```text
DRAFT
VALIDATED
APPROVED
POSTED
REVERSED
```

---

# 33. Journal Lines

## `journal_lines`

```text
id
journal_entry_id
account_id
department_id
cost_centre_id
branch_id
description
debit
credit
currency_id
exchange_rate
base_debit
base_credit
```

Database-level validation should enforce:

```text
debit >= 0
credit >= 0
```

and application/database logic must ensure a line cannot contain both debit and credit.

At journal level:

```text
SUM(debit) = SUM(credit)
```

before posting.

---

# 34. General Ledger

The preferred design is to treat the posted journal lines as the authoritative ledger dataset rather than creating a redundant mutable ledger.

A reporting view or materialized read model can expose:

```text
general_ledger
```

containing:

```text
account
date
journal
source
debit
credit
balance
entity
branch
department
cost centre
```

This avoids maintaining two financial truths.

---

# 35. Fixed Assets

## `asset_categories`

```text
id
legal_entity_id
name
code
asset_account_id
accumulated_depreciation_account_id
depreciation_expense_account_id
default_useful_life
depreciation_method
status
```

---

## `fixed_assets`

```text
id
legal_entity_id
asset_category_id
asset_code
name
serial_number
acquisition_date
capitalisation_date
acquisition_cost
residual_value
useful_life
depreciation_method
accumulated_depreciation
net_book_value
department_id
cost_centre_id
location
status
```

---

# 36. Asset Transactions

## `asset_transactions`

```text
id
fixed_asset_id
transaction_type
transaction_date
amount
source_type
source_id
description
```

Types:

```text
ACQUISITION
CAPITALISATION
DEPRECIATION
TRANSFER
REVALUATION
DISPOSAL
```

---

# 37. Depreciation

## `depreciation_runs`

```text
id
legal_entity_id
period_id
run_date
status
total_amount
posted_journal_id
```

Each depreciation run generates accounting entries.

---

# 38. HR

## `employees`

```text
id
legal_entity_id
employee_number
first_name
last_name
email
phone
department_id
branch_id
employment_status
hire_date
termination_date
status
```

---

## `employments`

```text
id
employee_id
employment_type
start_date
end_date
job_title
department_id
branch_id
status
```

---

# 39. Employee Compensation

## `employee_compensation`

```text
id
employee_id
effective_from
effective_to
basic_salary
pay_frequency
currency_id
status
```

Allowances and deductions should be separately configurable rather than embedding every possible payroll component into the employee table.

---

# 40. Payroll

## `payroll_periods`

```text
id
legal_entity_id
name
start_date
end_date
payment_date
status
```

---

## `payroll_runs`

```text
id
legal_entity_id
payroll_period_id
run_number
status
total_gross
total_deductions
total_net
posted_journal_id
```

---

## `payroll_items`

```text
id
payroll_run_id
employee_id
gross_pay
total_allowances
total_deductions
statutory_deductions
net_pay
status
```

---

## `payroll_components`

A flexible component model should support:

```text
BASIC
ALLOWANCE
DEDUCTION
TAX
PENSION
LOAN
ADVANCE
OTHER
```

Exact Nigerian statutory components will be finalized during the payroll research stage.

---

# 41. Employee Loans

## `employee_loans`

```text
id
employee_id
loan_type
principal_amount
outstanding_amount
start_date
repayment_start_date
repayment_frequency
installment_amount
status
```

Payroll deductions reference the employee loan.

---

# 42. Budgeting

## `budgets`

```text
id
legal_entity_id
name
fiscal_year
currency_id
status
```

---

## `budget_lines`

```text
id
budget_id
account_id
department_id
branch_id
cost_centre_id
financial_period_id
amount
```

---

## `budget_variances`

This should preferably be a derived/reporting structure rather than a manually maintained source table.

Concept:

```text
Budget
vs
Actual GL
=
Variance
```

---

# 43. Tax

## `tax_types`

```text
id
legal_entity_id
name
code
tax_category
status
```

---

## `tax_rates`

```text
id
tax_type_id
rate
effective_from
effective_to
status
```

---

## `tax_configurations`

```text
id
legal_entity_id
tax_type_id
rate_id
sales_account_id
purchase_account_id
payable_account_id
receivable_account_id
status
```

The exact Nigerian tax configuration should be populated after the dedicated tax research stage.

---

# 44. Approvals

## `approval_requests`

```text
id
legal_entity_id
entity_type
entity_id
requested_by
requested_at
status
current_level
```

---

## `approval_actions`

```text
id
approval_request_id
approver_id
level
action
comment
acted_at
```

Actions:

```text
APPROVE
REJECT
RETURN
```

This makes approval reusable across:

* invoices;
* payments;
* purchase orders;
* expenses;
* payroll;
* stock adjustments;
* journal entries.

---

# 45. Audit

## `audit_events`

```text
id
legal_entity_id
user_id
action
entity_type
entity_id
timestamp
ip_address
before_data
after_data
reason
request_id
```

`before_data` and `after_data` may use JSONB where appropriate.

Sensitive data must receive appropriate security controls.

---

# 46. Validation

## `validation_events`

```text
id
entity_type
entity_id
validation_type
severity
message
status
created_at
resolved_at
resolved_by
```

Severity:

```text
INFO
WARNING
ERROR
CRITICAL
```

Examples:

```text
Credit limit exceeded
Duplicate supplier invoice
Insufficient stock
Closed financial period
Unbalanced journal
Missing approval
```

---

# 47. Documents

## `documents`

```text
id
legal_entity_id
document_type
file_name
storage_key
mime_type
file_size
checksum
uploaded_by
uploaded_at
status
```

---

## `document_links`

```text
id
document_id
entity_type
entity_id
```

This allows one document to be associated with:

* invoice;
* purchase order;
* payment;
* expense;
* asset;
* employee;
* payroll run.

---

# 48. Critical Database Constraints

The database should enforce financial integrity wherever possible.

### Journal balance

A journal cannot be posted unless:

```text
SUM(debits) = SUM(credits)
```

### Positive amounts

Amounts should not be allowed to contain ambiguous negative debit/credit representations.

Use:

```text
debit >= 0
credit >= 0
```

### Period control

Posted transactions must reference an open financial period.

### Account control

Only active and postable accounts may receive journal lines.

### Entity isolation

Transactions cannot reference accounts belonging to another legal entity unless explicitly supported by an intercompany mechanism.

### Referential integrity

Posted records must not reference deleted master data.

---

# 49. Important Indexes

The development engine should create indexes around high-frequency financial queries.

Examples:

```text
legal_entity_id
customer_id
supplier_id
product_id
batch_id
account_id
financial_period_id
transaction_date
invoice_date
due_date
status
source_type + source_id
```

Composite indexes will be needed for common queries such as:

```text
customer + status
supplier + status
account + date
product + warehouse
batch + product
entity + period
bank_account + transaction_date
```

The final index strategy should be validated against actual query patterns after implementation.

---

# 50. Unique Constraints

Important business uniqueness rules include:

```text
organization.code
legal_entity.code
customer(customer/legal entity code)
supplier(supplier/legal entity code)
product(legal entity + SKU)
account(legal entity + code)
invoice(legal entity + invoice number)
purchase_order(legal entity + PO number)
journal(legal entity + journal number)
employee(legal entity + employee number)
```

Supplier invoice numbers should also support duplicate detection.

---

# 51. Database Transaction Model

Financial posting must occur inside a database transaction.

Conceptually:

```text
BEGIN

1. Lock/validate source transaction
2. Validate financial period
3. Validate accounts
4. Generate accounting event
5. Generate journal
6. Generate journal lines
7. Verify debit = credit
8. Update operational ledger state
9. Create audit event
10. Mark source as posted

COMMIT
```

Any failure:

```text
ROLLBACK
```

This prevents partial financial posting.

---

# 52. Optimistic vs Pessimistic Control

Normal editing can use optimistic concurrency.

Financial posting requires stronger controls.

For example, two users should not be able to simultaneously post changes that consume the same inventory balance without appropriate transaction isolation.

Inventory and financial posting therefore require database-level transactional protection.

---

# 53. Idempotency

Financial POST endpoints should support idempotency.

Example:

```text
POST /sales/invoices
Idempotency-Key: ABC123
```

If the same request arrives twice:

```text
Request 1 → Invoice created
Request 2 → Existing result returned
```

rather than:

```text
Invoice 1
Invoice 2
```

This is especially important for:

* payments;
* payroll;
* journal posting;
* bank imports;
* integrations.

---

# 54. API Transaction Pattern

Example invoice API:

```text
POST /api/v1/sales/invoices
```

Request:

```text
customer_id
invoice_date
due_date
lines[]
discounts[]
charges[]
taxes[]
```

The API should:

```text
validate
 ↓
save draft
```

Then:

```text
POST /api/v1/sales/invoices/{id}/approve
```

Then:

```text
POST /api/v1/sales/invoices/{id}/post
```

The posting endpoint invokes the accounting engine.

---

# 55. Accounting API

Controlled journal functionality:

```text
POST /api/v1/accounting/journals
GET  /api/v1/accounting/journals/{id}
POST /api/v1/accounting/journals/{id}/validate
POST /api/v1/accounting/journals/{id}/approve
POST /api/v1/accounting/journals/{id}/post
POST /api/v1/accounting/journals/{id}/reverse
```

The system should not expose arbitrary database mutation endpoints.

---

# 56. Reporting API

Examples:

```text
GET /api/v1/reports/trial-balance
GET /api/v1/reports/general-ledger
GET /api/v1/reports/income-statement
GET /api/v1/reports/balance-sheet
GET /api/v1/reports/cash-flow
GET /api/v1/reports/aged-receivables
GET /api/v1/reports/aged-payables
GET /api/v1/reports/inventory
GET /api/v1/reports/bank-reconciliation
GET /api/v1/reports/payroll
```

All reports should support relevant filters such as:

```text
legal_entity
branch
department
cost_centre
date_range
financial_period
account
customer
supplier
product
batch
```

---

# 57. Drill-Down API

A report should expose its lineage.

Example:

```text
GET /reports/income-statement
       ↓
GET /reports/accounts/{account_id}
       ↓
GET /accounting/journals/{journal_id}
       ↓
GET /sales/invoices/{invoice_id}
```

This creates the end-to-end audit path.

---

# 58. Frontend Contract

The frontend should consume domain APIs rather than directly querying PostgreSQL.

```text
React
  ↓
FastAPI
  ↓
Application Service
  ↓
Repository / Domain Logic
  ↓
PostgreSQL
```

This protects business rules.

---

# 59. Repository vs Service Logic

Repositories should handle data persistence.

Services should handle business logic.

Example:

```text
InvoiceRepository
    ↓
InvoiceService
    ↓
AccountingService
    ↓
PostingService
```

Do not put accounting rules inside SQL repositories.

---

# 60. Domain Events

The system should define standard event names.

Examples:

```text
customer.created
invoice.created
invoice.approved
invoice.posted
payment.received
payment.allocated
purchase.received
supplier_invoice.posted
inventory.adjusted
inventory.recalled
payroll.calculated
payroll.approved
payroll.posted
journal.posted
journal.reversed
period.closed
```

These can initially be internal application events.

They can later become infrastructure-level events if the platform grows.

---

# 61. Reporting Read Models

Complex dashboards should not repeatedly execute expensive accounting calculations against raw transaction tables.

Introduce read models such as:

```text
finance_dashboard_summary
ar_dashboard_summary
ap_dashboard_summary
inventory_dashboard_summary
cash_position_summary
payroll_dashboard_summary
```

These are **derived data**.

The source remains:

```text
Transactions → Accounting → GL
```

---

# 62. Rebuildability

A major architectural requirement:

> Derived financial views should be rebuildable from authoritative records.

For example:

```text
inventory_balances
dashboard summaries
report caches
analytics aggregates
```

should be reconstructable.

This is important for recovery, auditing and future system evolution.

---

# 63. Backup & Recovery

Because this replaces the client's core accounting system, database protection becomes a business-critical requirement.

The production architecture should eventually include:

```text
Primary PostgreSQL
       │
       ├── Automated backups
       ├── Point-in-time recovery
       ├── Backup verification
       └── Disaster recovery procedure
```

A backup that has never been tested for restoration should not be considered a reliable backup strategy.

---

# 64. Security Architecture

Financial information should be protected at multiple levels.

```text
Authentication
      ↓
Authorization
      ↓
Role Permission
      ↓
Legal Entity Scope
      ↓
Module Permission
      ↓
Record Access
```

Sensitive information includes:

* employee data;
* payroll;
* bank information;
* customer information;
* supplier information;
* financial transactions.

---

# 65. Row-Level Security

PostgreSQL Row-Level Security can become useful for multi-company deployments.

For example:

```text
User A
 → Entity A

User B
 → Entity B

Group Finance User
 → Entity A + Entity B
```

This should complement application-level authorization rather than replace it.

---

# 66. First Production Database Boundary

The first implementation should therefore target:

```text
PostgreSQL
│
├── Identity & Organization
├── Master Data
├── Sales / AR
├── Procurement / AP
├── Inventory
├── Banking
├── Accounting
├── Fixed Assets
├── HR / Payroll
├── Budgeting
├── Tax
├── Approvals
├── Audit
└── Documents
```

Do not introduce separate databases for each module at this stage.

The financial system benefits strongly from transactional consistency across these domains.

---

# 67. Database Build Order

The development engine should build migrations in this order:

### Migration 001

Organization and legal entities

### Migration 002

Users, roles and permissions

### Migration 003

Currencies and financial periods

### Migration 004

Chart of Accounts

### Migration 005

Customers and suppliers

### Migration 006

Products, warehouses and inventory master data

### Migration 007

Accounting events and journals

### Migration 008

General Ledger/reporting views

### Migration 009

Sales and AR

### Migration 010

Procurement and AP

### Migration 011

Inventory transactions

### Migration 012

Banking and reconciliation

### Migration 013

Fixed assets

### Migration 014

HR

### Migration 015

Payroll

### Migration 016

Budgeting

### Migration 017

Tax configuration

### Migration 018

Approvals

### Migration 019

Audit

### Migration 020

Documents

This ordering minimizes circular dependencies.

---

# 68. Seed Data

The system should have controlled seed data for:

* account types;
* standard statuses;
* currencies;
* transaction types;
* payment methods;
* inventory movement types;
* journal source types;
* approval actions.

The client's actual Chart of Accounts should be loaded as **client configuration**, not embedded permanently into application code.

---

# 69. Testing Strategy

Every financial module requires more than ordinary CRUD testing.

The test layers should include:

```text
Unit Tests
Integration Tests
Database Constraint Tests
Accounting Tests
Transaction Tests
Permission Tests
Reconciliation Tests
Reporting Tests
End-to-End Tests
```

---

# 70. Accounting Test Example

For a ₦1,000,000 invoice:

Expected:

```text
AR                  DR 1,000,000
Sales Revenue       CR 1,000,000
```

If inventory cost is ₦700,000:

```text
COGS                 DR 700,000
Inventory            CR 700,000
```

Then verify:

```text
Trial Balance
AR balance
Revenue
COGS
Inventory
Customer balance
GL
Income Statement
```

all remain internally consistent.

---

# 71. Core Invariant

The development engine should treat the following as a fundamental invariant:

```text
SUM(all posted debits)
=
SUM(all posted credits)
```

And:

```text
GL balance
=
sum(posted journal lines)
```

And:

```text
Customer balance
=
customer transactions
-
allocated settlements
```

And:

```text
Supplier balance
=
supplier obligations
-
allocated settlements
```

And:

```text
Inventory balance
=
valid inventory movements
```

These invariants should be tested continuously.

---

# 72. Development Engine Instruction

The development engine should interpret this document as an architectural specification, not as permission to make arbitrary implementation decisions.

Where the specification says:

**TBD / research required**

the engine must not invent business rules.

Instead it should:

1. create the architectural extension point;
2. mark the configuration as pending;
3. continue with unaffected modules.

This is particularly important for:

* Nigerian payroll;
* Nigerian tax;
* inventory costing;
* statutory deductions;
* depreciation policy;
* intercompany accounting.

---

# 73. Current Architecture Status

At this stage we have:

```text
CAPABILITY MATRIX
       ↓
WORKFLOW MAP
       ↓
ENTITY MAP
       ↓
BACKEND ARCHITECTURE
       ↓
DATABASE SPECIFICATION
```

The next layer is **API & Service Specification**.

That document will define:

* service responsibilities;
* endpoint-by-endpoint contracts;
* request/response structures;
* transaction commands;
* validation behaviour;
* posting behaviour;
* permissions;
* error handling;
* idempotency;
* frontend/backend boundaries.

After that, we can move into the **Frontend Architecture & Screen Map**, and then combine both into the final **Synbot Financial Development Specification** for the development engine.

# End of V1
