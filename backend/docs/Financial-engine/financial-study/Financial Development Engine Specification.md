# Synbot Financial Development Engine Specification

**Version:** 1.0
**Status:** Development Baseline
**Purpose:** Master implementation specification for replacing the client’s Sage 50 financial system with Synbot Financial OS.

---

# 1. Product Objective

Synbot Financial OS will replace the client's existing Sage-based financial workflow with a native, integrated financial platform.

Sage is therefore treated as:

* a source of historical business requirements;
* a reference for existing reports and workflows;
* a source of legacy data to understand;
* **not** a runtime dependency;
* **not** an integration target;
* **not** an export/import compatibility requirement.

The new platform must establish **one financial source of truth**.

The governing principle is:

> **One business event → one transaction → one accounting event → one journal → one ledger → many derived reports.**

Every financial module must ultimately flow through the accounting engine.

---

# 2. Product Architecture

## 2.1 Architecture Style

Build Synbot initially as a:

**Modular Monolith + PostgreSQL + React**

Do not begin with microservices.

The system should have strong internal domain boundaries so individual services can later be extracted if scale requires it.

### Backend

* Python
* FastAPI
* PostgreSQL
* SQLAlchemy
* Alembic
* Pydantic
* Redis where caching/background coordination is required
* Background workers for long-running jobs

### Frontend

* React
* TypeScript
* Vite
* React Router
* API client layer
* reusable financial components
* role-aware navigation
* responsive desktop-first interface

### AI Layer

AI sits **above** the financial system.

AI may:

* query;
* explain;
* summarize;
* detect anomalies;
* identify trends;
* generate management insights.

AI must **not directly mutate accounting records**.

All financial mutations must pass through normal backend services and controls.

---

# 3. Domain Architecture

The backend shall be divided into the following domains:

```text
synbot/
│
├── organization/
├── identity/
├── master_data/
│
├── sales/
├── receivables/
│
├── procurement/
├── payables/
│
├── inventory/
├── banking/
│
├── accounting/
├── fixed_assets/
│
├── hr/
├── payroll/
│
├── budgeting/
├── tax/
│
├── approvals/
├── audit/
├── documents/
├── reporting/
└── intelligence/
```

The accounting domain is the central financial authority.

---

# 4. Organization & Multi-Company Model

Synbot must support multiple companies from the beginning.

Hierarchy:

```text
Organization
    │
    ├── Legal Entity
    │      ├── Branch
    │      ├── Department
    │      └── Cost Centre
    │
    └── Users / Roles / Permissions
```

Every relevant financial record should carry sufficient organizational scope.

Minimum isolation dimensions:

* organization
* legal entity
* branch
* department
* cost centre

This allows Synbot to eventually operate as a multi-company financial platform without redesigning the database.

---

# 5. Financial Master Data

The following are foundational entities.

## Organization

* organization
* legal entity
* branch
* department
* cost centre

## Accounting

* currency
* financial period
* account group
* chart of accounts
* account

## Commercial

* customer
* customer contact
* supplier
* supplier contact
* payment terms

## Inventory

* product category
* product
* unit of measure
* warehouse
* warehouse location
* batch

## Financial Infrastructure

* bank account
* cash account
* tax type
* tax rate

## People

* employee
* employment
* compensation
* payroll configuration

---

# 6. Chart of Accounts

The Chart of Accounts must be dynamic.

Users with appropriate permissions should be able to create:

* income accounts;
* expense accounts;
* asset accounts;
* liability accounts;
* equity accounts;
* inventory accounts;
* COGS accounts;
* tax accounts;
* other income accounts;
* other relevant control accounts.

An account can be:

* active;
* inactive;
* postable;
* non-postable;
* control account.

Once an account has financial history, it must not simply be deleted.

It should be deactivated.

The client's existing Sage COA contains approximately 465 accounts and can be used as an initial migration/reference dataset.

---

# 7. The Accounting Engine

This is the most important component of Synbot Financial OS.

Every financial transaction must eventually produce an accounting event.

```text
Business Event
      ↓
Validation
      ↓
Accounting Rule Resolution
      ↓
Journal Entry
      ↓
Journal Lines
      ↓
POST
      ↓
General Ledger
      ↓
Financial Statements
      ↓
Reporting / Intelligence
```

## Core Accounting Services

### PostingService

Responsible for:

1. validate transaction;
2. resolve accounting rules;
3. construct journal;
4. validate debit/credit balance;
5. verify financial period;
6. post;
7. create audit event;
8. commit atomically.

### AccountingRuleService

Determines:

* debit account;
* credit account;
* tax treatment;
* inventory treatment;
* revenue classification;
* COGS treatment;
* other income;
* discounts;
* charges.

### GeneralLedgerService

Reads posted journal lines and provides:

* account history;
* debit totals;
* credit totals;
* opening balances;
* closing balances;
* transaction drill-down.

---

# 8. Accounting Invariants

These are non-negotiable.

### Rule 1 — Every posted journal balances

```text
SUM(debits) = SUM(credits)
```

### Rule 2 — Closed periods cannot receive postings.

### Rule 3 — Inactive accounts cannot receive postings.

### Rule 4 — Non-postable accounts cannot receive direct postings.

### Rule 5 — Posted transactions cannot be silently edited.

Corrections must occur through:

* reversal;
* correction;
* replacement transaction.

### Rule 6 — Financial mutation must be idempotent.

### Rule 7 — Financial posting must be atomic.

If any critical part fails:

```text
ROLLBACK
```

No partial financial transaction should remain.

---

# 9. Universal Transaction Lifecycle

Where applicable:

```text
DRAFT
   ↓
VALIDATING
   ↓
PENDING APPROVAL
   ↓
APPROVED
   ↓
POSTED
   ↓
RECONCILED
   ↓
CLOSED
```

Not every transaction requires every state.

For example, low-risk transactions may bypass approval according to configured rules.

---

# 10. Sales & Accounts Receivable

Core lifecycle:

```text
Customer
   ↓
Quote
   ↓
Sales Order
   ↓
Delivery
   ↓
Invoice
   ↓
AR
   ↓
Payment
   ↓
Allocation
   ↓
Reconciliation
```

The system must support:

* customer profiles;
* customer credit limits;
* payment terms;
* invoices;
* partial payments;
* overpayments;
* credit notes;
* returns;
* write-offs;
* customer statements;
* customer ageing;
* customer transaction history.

## Credit Control

Before posting a credit sale:

```text
Current AR Exposure
+
New Invoice
-
Eligible Credits
≤
Credit Limit
```

If the threshold is exceeded:

* warn;
* block;
* or request authorized override.

The behaviour must be configurable.

---

# 11. Sales Invoice Accounting

Typical invoice:

```text
DR Accounts Receivable
CR Sales Revenue
```

If inventory is involved:

```text
DR Cost of Goods Sold
CR Inventory
```

Tax and other charges must be handled according to configured accounting rules.

Delivery charges must not automatically disappear into sales revenue.

The meeting requirements specifically identified the need to classify delivery charges and other income/charges separately. This should therefore be configurable in the accounting rules engine.

---

# 12. Customer Returns

Return workflow:

```text
Return Request
      ↓
Original Sale
      ↓
Product / Batch Validation
      ↓
Inspection
      ↓
Approval
      ↓
Inventory Movement
      ↓
Credit Note / Refund
      ↓
Accounting
      ↓
Audit
```

The system must preserve the relationship between the original sale and the return.

---

# 13. Accounts Payable

Core workflow:

```text
Supplier
   ↓
Purchase Request
   ↓
Purchase Order
   ↓
Goods Receipt
   ↓
Supplier Invoice
   ↓
AP
   ↓
Payment
   ↓
Supplier Ledger
```

Supplier invoice validation should include:

* supplier;
* invoice number;
* duplicate invoice check;
* PO;
* goods receipt;
* quantities;
* prices;
* tax;
* approval;
* payment terms.

Where applicable, Synbot should perform a three-way match:

```text
PO
+
Goods Receipt
+
Supplier Invoice
```

---

# 14. Supplier Returns

```text
Supplier Return
      ↓
Original Goods Receipt
      ↓
Product / Batch
      ↓
Approval
      ↓
Inventory Reduction
      ↓
AP Adjustment
      ↓
Accounting
```

---

# 15. Inventory Engine

Inventory is not merely a stock-counting module.

It must be financially connected.

Supported movement types:

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

The client's existing inventory exports include valuation, stock status, unit activity, item costing, COGS journal, item master, pricing and buyer information. The existing Unit Activity report specifically demonstrates beginning quantity, purchases, sales and closing quantity.

---

# 16. Inventory Ledger

The authoritative inventory history is:

```text
Inventory Transactions
```

`inventory_balances` should be treated as a derived/read model.

For each product/batch:

```text
Opening
+
Purchases
+
Returns In
+
Transfers In
+
Adjustments
-
Sales
-
Returns Out
-
Transfers Out
-
Damage
-
Expiry
=
Closing
```

Every financially relevant inventory movement must have corresponding accounting treatment.

---

# 17. Batch Traceability

Products requiring batch control must support:

* batch number;
* manufacturing date;
* expiry date;
* unit cost;
* warehouse;
* current quantity;
* status.

The user must be able to search:

```text
Batch
 ↓
Inventory History
 ↓
Sales
 ↓
Invoices
 ↓
Customers
 ↓
Quantities
```

This is particularly important for recalls.

---

# 18. Recall Workflow

```text
Select Batch
      ↓
Identify Outbound Transactions
      ↓
Identify Customers
      ↓
Identify Invoices
      ↓
Identify Quantities
      ↓
Create Recall
      ↓
Notify / Track Returns
      ↓
Quarantine
      ↓
Disposition
      ↓
Financial Adjustment
      ↓
Close Recall
```

Recall actions must be auditable.

---

# 19. Stock Loan

A stock loan must **not** be treated as a sale.

```text
Stock Loan
   ↓
Loan Record
   ↓
Original Batch
   ↓
Quantity
   ↓
Expected Return
```

No sales revenue or normal customer AR should be created merely because inventory leaves under a loan arrangement.

On return:

* returned quantity;
* returned batch;
* replacement batch;
* remaining balance

must all be tracked.

The meeting requirements explicitly identified this as a distinct workflow.

---

# 20. Inventory Adjustment

Adjustment workflow:

```text
Adjustment Request
      ↓
Current System Quantity
      ↓
Physical Count
      ↓
Variance
      ↓
Reason
      ↓
Approval
      ↓
Inventory Movement
      ↓
Accounting
      ↓
Audit
```

Reasons should be configurable:

* shortage;
* excess;
* damage;
* expiry;
* count correction;
* system correction;
* other approved reason.

---

# 21. Banking & Cash

Banking must include:

* bank accounts;
* cash accounts;
* deposits;
* withdrawals;
* transfers;
* bank charges;
* cash lodgements;
* bank statements;
* reconciliation.

Example:

### Cash → Bank

```text
DR Bank
CR Cash
```

### Customer payment

```text
DR Bank/Cash
CR Accounts Receivable
```

---

# 22. Bank Reconciliation

Workflow:

```text
Bank Statement
      ↓
Import / Capture Transactions
      ↓
Auto Matching
      ↓
Manual Review
      ↓
Exceptions
      ↓
Reconciliation
```

Statuses:

* matched;
* likely match;
* unmatched;
* duplicate;
* exception.

The existing client evidence shows account reconciliation is one of the complete areas of the legacy reporting set.

---

# 23. General Journal

Manual journals are allowed but controlled.

Use cases include:

* asset purchases;
* depreciation;
* corrections;
* transfers;
* reclassification;
* opening balances;
* approved accounting adjustments.

Every journal must pass:

```text
Account Validation
+
Period Validation
+
Balance Validation
+
Approval
+
Audit
```

---

# 24. Fixed Assets

Asset categories should include, where applicable:

* furniture;
* fittings;
* plant/machinery;
* office equipment;
* land/buildings;
* investments.

Lifecycle:

```text
Acquisition
 ↓
Capitalisation
 ↓
Depreciation
 ↓
Transfer / Revaluation
 ↓
Disposal
 ↓
Gain/Loss
```

Straight-line depreciation should be supported initially.

Typical depreciation:

```text
DR Depreciation Expense
CR Accumulated Depreciation
```

---

# 25. Payroll + HR

Payroll remains a core Synbot module.

It must connect directly to the Staff/HR dashboard.

## Employee lifecycle

```text
Employee
 ↓
Employment
 ↓
Compensation
 ↓
Attendance / Leave
 ↓
Allowances
 ↓
Deductions
 ↓
Payroll
 ↓
Payslip
 ↓
Payment
 ↓
Payroll Journal
 ↓
GL
```

Payroll must support:

* employee master;
* employment status;
* salary structure;
* allowances;
* deductions;
* attendance;
* leave;
* overtime;
* payroll periods;
* payroll runs;
* payslips;
* employee loans/advances;
* payroll approval;
* payroll posting.

### Important research gate

The exact Nigerian statutory payroll/tax implementation is **not yet considered finalized**.

Do not hard-code statutory rules until they have been researched and approved.

---

# 26. HR → Payroll Integration

Changes to:

* salary;
* allowances;
* deductions;
* employment status;
* effective dates

must flow from HR into payroll through controlled changes.

Example:

```text
HR Compensation Change
       ↓
Approval
       ↓
Effective Date
       ↓
Payroll Configuration
       ↓
Next Payroll Run
```

---

# 27. Employee Loans & Advances

```text
Employee Request
      ↓
Approval
      ↓
Disbursement
      ↓
Staff Receivable
      ↓
Payroll Deduction
      ↓
Balance Reduction
      ↓
Closed
```

This must connect HR, payroll and accounting.

---

# 28. Budgeting

Budgets must support:

* financial period;
* account;
* department;
* branch;
* cost centre;
* budget amount;
* actual;
* variance;
* forecast.

Core views:

```text
Budget
Actual
Variance
Variance %
Forecast
```

The legacy system already contains budget comparison statements, so budget-vs-actual reporting is part of the target requirement.

---

# 29. Financial Reporting Engine

Reports must be **derived from the accounting truth**, not manually maintained datasets.

Minimum reports:

## Financial Statements

* Balance Sheet
* Income Statement
* Cash Flow Statement
* Retained Earnings
* Statement of Financial Position
* Income vs Budget
* Revenue & Expenses vs Budget
* General Ledger Account Summary
* Trial Balance

## General Ledger

* General Ledger
* General Journal
* Chart of Accounts
* Account Register
* Account Variance

## AR

* Aged Receivables
* Customer Ledger
* Customer Transaction History
* Sales Journal
* Cash Receipts Journal
* Invoice Register
* Customer Statement
* Customer Balance

## AP

* Aged Payables
* Vendor Ledger
* Purchase Journal
* Supplier Transaction History
* Open Supplier Invoices
* Cash Disbursements
* Supplier Statement

## Inventory

* Inventory Valuation
* Stock Status
* Unit Activity
* Item Costing
* COGS Journal
* Inventory Adjustment Journal
* Inventory Profitability
* Stock Reorder
* Physical Stock Count
* Batch History

## Banking

* Bank Register
* Cash Register
* Bank Reconciliation
* Outstanding Items
* Deposits
* Withdrawals

## Payroll

* Payroll Register
* Payslips
* Payroll Summary
* Employee Deductions
* Payroll Journal

The existing Sage report inventory gives the development team a concrete benchmark for the report coverage required, including the missing AP Cash Disbursements and Inventory Adjustment reports that should be native in Synbot rather than copied as Sage compatibility features.

---

# 30. Reporting Requirements

Every report should support, where meaningful:

* date range;
* company;
* legal entity;
* branch;
* department;
* cost centre;
* account;
* customer;
* supplier;
* product;
* batch;
* status.

Reports must support drill-down.

Example:

```text
Income Statement
     ↓
Revenue
     ↓
Account
     ↓
Journal
     ↓
Invoice
     ↓
Customer
```

The user should be able to move from a management number to its underlying transaction.

---

# 31. Financial Control Engine

Synbot must actively prevent accounting errors.

Controls include:

### Transaction controls

* duplicate detection;
* required fields;
* valid references;
* valid period;
* valid accounts;
* approval rules;
* credit limits;
* inventory availability;
* batch validity;
* tax validation.

### Accounting controls

* balanced journal;
* valid account;
* active period;
* correct entity;
* duplicate reference;
* valid currency;
* valid accounting rule.

### Reconciliation controls

* AR vs customer balances;
* AP vs supplier balances;
* inventory vs inventory GL;
* bank vs bank ledger;
* payroll vs payroll journal;
* trial balance;
* balance sheet integrity.

The meeting requirements specifically call for internal accounting review and flagging discrepancies rather than allowing imbalance to pass silently.

---

# 32. Audit Engine

Every important financial event must create an audit record.

Audit should capture:

* user;
* timestamp;
* organization;
* entity;
* action;
* source transaction;
* previous state where applicable;
* new state where applicable;
* approval;
* IP/session metadata where appropriate;
* reason/comment.

Financial history must be immutable.

---

# 33. Approval Engine

Approval should be configurable rather than hard-coded.

Example:

```text
Transaction
    ↓
Rule Evaluation
    ↓
Approval Required?
   ↙       ↘
 NO        YES
 ↓          ↓
POST      Approval Queue
             ↓
          Approved
             ↓
            POST
```

Rules may depend on:

* amount;
* department;
* transaction type;
* account;
* employee role;
* company;
* branch.

---

# 34. Period Close

Period close is a controlled financial operation.

Before closing:

```text
Check Unposted Transactions
Check Unbalanced Journals
Check AR Reconciliation
Check AP Reconciliation
Check Inventory Reconciliation
Check Bank Reconciliation
Check Payroll
Check Trial Balance
Check Critical Exceptions
```

If critical issues remain:

```text
BLOCK CLOSE
```

Only authorized finance users can close a period.

---

# 35. Frontend Application Shell

Primary navigation:

```text
Dashboard
Finance
Sales
Procurement
Inventory
Banking
HR & Payroll
Fixed Assets
Budgeting
Reports
Intelligence
Documents
Administration
```

Global components:

* company switcher;
* global search;
* notifications;
* user profile;
* alerts;
* financial period indicator.

---

# 36. Finance Workspace

Screens:

```text
Finance Overview
General Ledger
Chart of Accounts
Journals
Accounts Receivable
Accounts Payable
Banking
Fixed Assets
Budgeting
Tax
Period Close
```

The Finance Control Tower should highlight:

* revenue;
* expenses;
* profit;
* cash;
* AR;
* AP;
* inventory value;
* overdue receivables;
* overdue payables;
* reconciliation exceptions;
* approval exceptions.

---

# 37. Sales Workspace

Screens:

```text
Sales Overview
Customers
Quotes
Orders
Deliveries
Invoices
Credit Notes
Returns
Sales Reports
```

Customer 360:

```text
Customer
 ├── Profile
 ├── Orders
 ├── Invoices
 ├── Payments
 ├── Outstanding Balance
 ├── Ageing
 ├── Credit Limit
 ├── Products Purchased
 └── Timeline
```

---

# 38. Procurement Workspace

```text
Procurement Overview
Purchase Requests
Purchase Orders
Goods Receipts
Supplier Invoices
Supplier Returns
Supplier Reports
```

Supplier 360 should expose:

* supplier profile;
* POs;
* receipts;
* invoices;
* payments;
* balance;
* ageing;
* transaction timeline.

---

# 39. Inventory Workspace

```text
Inventory Overview
Products
Stock
Batches
Transfers
Adjustments
Returns
Stock Loans
Recalls
Stock Counts
Inventory Reports
```

Product 360:

```text
Product
 ├── Master Data
 ├── Current Stock
 ├── Batch
 ├── Movement
 ├── Purchases
 ├── Sales
 ├── Returns
 ├── Cost
 ├── Price
 └── Profitability
```

---

# 40. HR & Payroll Workspace

```text
Staff Dashboard
Employees
Organization
Attendance
Leave
Compensation
Payroll
Staff Loans
HR Reports
```

Employee 360:

```text
Employee
 ├── Profile
 ├── Employment
 ├── Compensation
 ├── Attendance
 ├── Leave
 ├── Payroll
 ├── Loans
 ├── Documents
 └── Timeline
```

---

# 41. Intelligence Layer

The AI layer should sit above all approved data.

Example questions:

> What caused the reduction in gross margin this month?

> Which customers are overdue?

> Which products are generating the highest revenue?

> Which inventory items have unusual movement?

> What expenses increased significantly this month?

> Which supplier balances are approaching due date?

The response should contain:

```text
Answer
↓
Key Metrics
↓
Drivers
↓
Supporting Transactions
↓
Relevant Reports
↓
Suggested Investigation
```

The Finance AI must be read-only unless a future explicitly approved workflow introduces controlled actions.

---

# 42. API Architecture

Base:

```text
/api/v1/
```

Use REST resources for standard CRUD.

Use explicit command endpoints for business actions.

Example:

```http
POST /sales/invoices/{id}/approve
POST /sales/invoices/{id}/post
POST /sales/invoices/{id}/void
```

Instead of allowing clients to manipulate financial status arbitrarily.

---

# 43. Core API Domains

```text
/organizations
/legal-entities
/branches
/departments
/cost-centres

/accounts
/financial-periods
/currencies

/customers
/suppliers
/products
/batches

/sales-orders
/deliveries
/sales-invoices
/credit-notes
/customer-payments

/purchase-requests
/purchase-orders
/goods-receipts
/supplier-invoices
/supplier-payments

/inventory
/bank-accounts
/bank-statements
/reconciliations

/journals
/general-ledger
/trial-balance

/fixed-assets

/employees
/attendance
/leave
/payroll
/employee-loans

/budgets
/taxes

/approvals
/audit
/documents
/reports
/intelligence
```

---

# 44. API Mutation Rules

Financial mutation endpoints should support:

```http
Idempotency-Key
X-Request-ID
Authorization
```

Standard errors:

```text
AUTHENTICATION_REQUIRED
PERMISSION_DENIED
RESOURCE_NOT_FOUND
VALIDATION_FAILED
DUPLICATE_RESOURCE
PERIOD_CLOSED
ACCOUNT_INACTIVE
ACCOUNT_NOT_POSTABLE
UNBALANCED_JOURNAL
APPROVAL_REQUIRED
CREDIT_LIMIT_EXCEEDED
INSUFFICIENT_STOCK
INVALID_BATCH
DUPLICATE_INVOICE
RECONCILIATION_EXCEPTION
TRANSACTION_ALREADY_POSTED
INVALID_STATE_TRANSITION
IDEMPOTENCY_CONFLICT
```

---

# 45. Database Architecture

PostgreSQL is the primary source of truth.

Major table groups:

```text
organizations
legal_entities
branches
departments
cost_centres

currencies
financial_periods
account_groups
accounts

customers
customer_contacts
suppliers
supplier_contacts

products
product_categories
units_of_measure
warehouses
warehouse_locations
batches

sales_orders
sales_order_lines
deliveries
delivery_lines
sales_invoices
sales_invoice_lines
credit_notes
credit_note_lines
customer_payments
payment_allocations

purchase_requests
purchase_orders
purchase_order_lines
goods_receipts
goods_receipt_lines
supplier_invoices
supplier_invoice_lines
supplier_payments
supplier_returns

inventory_transactions
inventory_balances

bank_accounts
cash_accounts
bank_transactions
bank_statements
bank_statement_transactions
bank_reconciliations
reconciliation_items

accounting_events
journal_entries
journal_lines

asset_categories
fixed_assets
asset_transactions
depreciation_runs

employees
employments
employee_compensation
attendance
leave

payroll_periods
payroll_runs
payroll_items
payroll_components
employee_loans

budgets
budget_lines

tax_types
tax_rates
tax_configurations

approval_requests
approval_actions

audit_events
validation_events

documents
document_links
```

---

# 46. Source-of-Truth Rules

This must be enforced throughout development.

| Information          | Authority            |
| -------------------- | -------------------- |
| Customer identity    | Customer Master      |
| Supplier identity    | Supplier Master      |
| Employee identity    | HR                   |
| Product identity     | Product Master       |
| Stock history        | Inventory Ledger     |
| Financial truth      | Posted Journal / GL  |
| Financial statements | Reporting Engine     |
| Audit history        | Audit Engine         |
| Payroll result       | Approved Payroll Run |
| Budget               | Approved Budget      |
| AI insight           | Derived/read-only    |

Do not create competing sources of financial truth.

---

# 47. Backend Development Rules for the Development Engine

The development engine/agents must follow these rules.

### Rule A

Never implement financial logic directly inside a frontend component.

### Rule B

Never allow an AI agent to write directly to financial tables.

### Rule C

Never create a second accounting implementation inside a module.

### Rule D

All financial postings go through `PostingService`.

### Rule E

All business mutations must validate state transitions.

### Rule F

All financial mutations must be transactional.

### Rule G

Never silently modify posted transactions.

### Rule H

Never guess tax or statutory rules.

### Rule I

Never hard-code company-specific accounting rules where configuration is appropriate.

### Rule J

Never delete financial history.

### Rule K

Every cross-domain mutation must have an explicit service boundary.

---

# 48. Frontend Development Rules

Frontend agents must:

* consume APIs;
* never calculate authoritative accounting results;
* respect permissions;
* respect company scope;
* respect financial period state;
* show transaction consequences before posting;
* expose audit history;
* expose approval status;
* provide drill-down;
* handle exceptions visibly.

Financial values displayed on dashboards should originate from backend reporting/query endpoints.

---

# 49. Development Sequence

Do not build everything simultaneously.

## Phase 1 — Foundation

Build:

* project structure;
* authentication;
* authorization;
* organization;
* legal entities;
* branches;
* departments;
* users;
* roles;
* permissions;
* currencies;
* financial periods;
* audit foundation.

### Exit Gate

A user can securely enter the correct company/entity context.

---

## Phase 2 — Financial Master Data

Build:

* COA;
* accounts;
* customers;
* suppliers;
* products;
* warehouses;
* batches;
* tax configuration framework;
* payment terms.

### Exit Gate

All core entities can be created, validated and scoped correctly.

---

## Phase 3 — Accounting Core

Build:

* accounting events;
* journals;
* journal lines;
* PostingService;
* AccountingRuleService;
* GL;
* Trial Balance;
* reversal;
* period controls.

### Exit Gate

A manual journal can be created, validated, approved, posted and reversed while maintaining:

```text
Debits = Credits
```

---

# 50. Phase 4 — Sales + AR

Build:

* customers;
* orders;
* deliveries;
* invoices;
* credit notes;
* payments;
* allocation;
* ageing;
* statements;
* credit limits.

### Exit Gate

A credit sale automatically produces the correct AR/revenue/inventory/COGS accounting.

---

# 51. Phase 5 — Procurement + AP

Build:

* purchase requests;
* POs;
* goods receipts;
* supplier invoices;
* three-way matching;
* supplier payments;
* supplier returns;
* ageing.

### Exit Gate

A complete procure-to-pay transaction reaches the GL automatically.

---

# 52. Phase 6 — Inventory

Build:

* stock ledger;
* balances;
* batch tracking;
* transfers;
* adjustments;
* stock counts;
* returns;
* stock loans;
* recalls;
* inventory valuation;
* COGS.

### Exit Gate

Inventory and accounting remain synchronized through every supported movement.

---

# 53. Phase 7 — Banking

Build:

* bank accounts;
* cash accounts;
* transactions;
* statement ingestion;
* matching;
* reconciliation;
* cash lodgement;
* exceptions.

### Exit Gate

Bank reconciliation can prove the relationship between bank records and Synbot's accounting records.

---

# 54. Phase 8 — Fixed Assets

Build:

* asset register;
* acquisition;
* capitalization;
* depreciation;
* transfer;
* disposal;
* gain/loss.

### Exit Gate

Depreciation produces correct accounting entries and asset balances.

---

# 55. Phase 9 — HR + Payroll

Build:

* employee master;
* employment;
* compensation;
* attendance;
* leave;
* allowances;
* deductions;
* payroll calculation;
* approval;
* payslips;
* payment;
* payroll journal;
* employee loans.

### Exit Gate

An approved payroll run produces correct employee results and accounting entries.

**Statutory Nigerian rules must be finalized before production payroll is enabled.**

---

# 56. Phase 10 — Budgeting + Tax

Build:

* budgets;
* budget approvals;
* actual-vs-budget;
* variance;
* tax engine;
* tax reporting.

### Exit Gate

Approved budget and tax configurations produce reproducible reports.

---

# 57. Phase 11 — Reporting

Build the reporting engine after the accounting foundation is stable.

Priority:

```text
Trial Balance
↓
GL
↓
Balance Sheet
↓
Income Statement
↓
Cash Flow
↓
AR/AP
↓
Inventory
↓
Banking
↓
Payroll
↓
Management Reports
```

This ordering prevents reports from becoming independently maintained calculations.

---

# 58. Phase 12 — Intelligence

Only after the underlying financial data is reliable:

Build:

* Finance AI;
* anomaly detection;
* trend analysis;
* cash forecasting;
* margin analysis;
* management insights.

The AI layer should consume trusted financial data rather than attempting to establish financial truth itself.

---

# 59. Golden Financial Test Suite

The development engine must automatically test at least:

### Accounting

* balanced journal;
* unbalanced journal rejected;
* closed-period posting rejected;
* inactive account rejected.

### Sales

* cash sale;
* credit sale;
* partial payment;
* overpayment;
* customer return;
* credit note.

### Procurement

* purchase;
* goods receipt;
* supplier invoice;
* supplier payment;
* supplier return.

### Inventory

* purchase;
* sale;
* transfer;
* adjustment;
* damage;
* expiry;
* batch replacement;
* stock loan;
* stock loan return;
* recall.

### Banking

* customer receipt;
* cash lodgement;
* bank transfer;
* reconciliation;
* duplicate statement transaction.

### Assets

* acquisition;
* capitalization;
* depreciation;
* disposal.

### Payroll

* payroll calculation;
* allowance;
* deduction;
* staff loan deduction;
* payroll posting.

### Controls

* duplicate invoice;
* credit limit breach;
* insufficient stock;
* unauthorized approval;
* invalid state transition;
* idempotency conflict.

---

# 60. Acceptance Standard

A module is **not complete** because its screen works.

A module is complete only when:

```text
Frontend
   ↓
API
   ↓
Domain Service
   ↓
Validation
   ↓
Accounting Event
   ↓
Journal
   ↓
GL
   ↓
Audit
   ↓
Report
```

works correctly where financially applicable.

---

# 61. Research Gates — Do Not Guess

The following remain explicit research items.

## R1 — Nigerian Payroll

Confirm current applicable:

* PAYE;
* pension;
* statutory deductions;
* employee/employer contributions;
* payroll reporting;
* relevant thresholds;
* filing requirements.

## R2 — Nigerian Tax

Confirm:

* VAT;
* WHT;
* applicable corporate tax treatment;
* tax invoice requirements;
* tax reporting;
* exemptions;
* sector-specific rules where applicable.

## R3 — Inventory Costing

Confirm the client's accounting policy:

* FIFO;
* weighted average;
* standard cost;
* batch costing;
* treatment of returns;
* treatment of adjustments.

Do not select the production method merely because Sage used one.

## R4 — Procurement

Confirm whether the client actually requires:

* purchase requisitions;
* POs;
* approvals;
* GRNs;
* partial receipts;
* supplier returns;
* three-way matching.

## R5 — Sales

Confirm:

* quote usage;
* sales orders;
* delivery notes;
* invoice timing;
* customer deposits;
* credit notes;
* write-offs;
* sales commissions.

## R6 — Fixed Assets

Confirm:

* capitalization threshold;
* useful lives;
* residual values;
* depreciation frequency;
* disposal policy;
* revaluation policy.

## R7 — Banking

Confirm:

* manual statement upload;
* bank feed;
* supported banks;
* transaction matching;
* reconciliation ownership.

## R8 — Multi-Company

Confirm:

* legal entities;
* intercompany transactions;
* shared customers;
* shared suppliers;
* shared products;
* consolidated reporting;
* intercompany elimination requirements.

---

# 62. Migration Strategy

Because Synbot is replacing Sage rather than integrating with it, migration must be treated as a controlled cutover.

Migration stages:

```text
Legacy Data Discovery
       ↓
Data Mapping
       ↓
Transformation
       ↓
Validation
       ↓
Trial Migration
       ↓
Reconciliation
       ↓
User Acceptance
       ↓
Opening Balances
       ↓
Cutover
       ↓
Synbot Becomes System of Record
```

The historical Sage reports currently provide useful evidence for validating migrated balances and report outputs. The existing snapshot ties through 30 June 2026, which gives us a practical baseline for reconciliation.

No ongoing Sage export/import workflow should be built into the production architecture.

---

# 63. Initial Migration Validation

At cutover, reconcile at minimum:

```text
Cash
Bank
AR
AP
Inventory
Fixed Assets
Liabilities
Equity
Revenue
Expenses
Retained Earnings
Trial Balance
```

The target condition is:

```text
Synbot Trial Balance
=
Approved Legacy Closing Position
```

subject to documented migration adjustments.

---

# 64. Report Validation Strategy

For reports with reliable historical Sage evidence:

```text
Sage Historical Report
        ↓
Expected Result
        ↓
Synbot Report
        ↓
Difference Analysis
```

Do not attempt to reproduce Sage's internal implementation.

Reproduce the **business result**.

Where the legacy report itself is missing, define the desired Synbot report from the business workflow rather than treating absence in Sage as evidence that the capability is unnecessary.

This is especially relevant for:

* Cash Disbursements;
* Inventory Adjustments;
* Inventory Profitability;
* Reorder;
* Physical Inventory;
* Audit;
* Payroll.

## The legacy inventory shows the Inventory Adjustment Journal missing, while payroll has no historical records because the Sage employee file is empty.

# 65. Definition of Done

A Synbot Financial feature is production-ready only when all applicable conditions are true:

### Functional

* workflow implemented;
* validation implemented;
* permissions implemented;
* approval implemented where required;
* accounting implemented;
* reporting implemented;
* audit implemented.

### Technical

* database migration;
* API;
* service layer;
* frontend;
* tests;
* error handling;
* logging;
* idempotency;
* documentation.

### Financial

* accounting entry verified;
* debit/credit verified;
* GL verified;
* report impact verified;
* reconciliation verified.

### Security

* authorization verified;
* company isolation verified;
* role permissions verified;
* audit trail verified.

### UX

* loading states;
* error states;
* empty states;
* confirmation;
* transaction consequences;
* drill-down.

---

# 66. Development Engine Instruction

The development engine should treat this specification as the governing contract.

When generating implementation work:

1. Identify the domain.
2. Identify the business workflow.
3. Identify required entities.
4. Identify database changes.
5. Identify service changes.
6. Identify accounting impact.
7. Identify API changes.
8. Identify frontend screens/components.
9. Identify permissions.
10. Identify audit requirements.
11. Identify tests.
12. Identify unresolved research gates.
13. Refuse to invent missing financial rules.
14. Produce implementation in dependency order.

Every implementation task should therefore answer:

```text
WHAT
WHY
DATA
WORKFLOW
API
SERVICE
ACCOUNTING
UI
PERMISSIONS
AUDIT
TESTS
ACCEPTANCE
```

---

# 67. Master Dependency Graph

```text
FOUNDATION
    ↓
MASTER DATA
    ↓
ACCOUNTING CORE
    ↓
┌───────────────┬───────────────┐
│               │               │
SALES          PROCUREMENT     BANKING
│               │               │
AR              AP              CASH
│               │               │
└───────┬───────┴───────┬───────┘
        ↓               ↓
      INVENTORY      FIXED ASSETS
        │               │
        └───────┬───────┘
                ↓
             PAYROLL
                ↓
          BUDGET / TAX
                ↓
             REPORTING
                ↓
           INTELLIGENCE
```

---

# 68. The Core Design Principle

Synbot should not become:

> “Sage, but built with React and FastAPI.”

It should become:

> **A unified financial operating system in which commercial activity, inventory, banking, HR, payroll and accounting are connected by one transaction and accounting engine.**

The most important architectural decision is therefore not the UI, AI, or individual report.

It is the **accounting/event architecture** underneath everything.

If that layer is correct, the dashboards, reports, AI, reconciliation and management intelligence can all be derived from the same financial truth.

---

# 69. Immediate Development Order

The development engine should now work in this exact order:

```text
01  Foundation
02  Organization / Multi-company
03  Identity / RBAC
04  Financial periods
05  Chart of Accounts
06  Master Data
07  Accounting Engine
08  Journal / GL
09  Sales / AR
10  Procurement / AP
11  Inventory
12  Banking
13  Fixed Assets
14  HR
15  Payroll
16  Budgeting
17  Tax
18  Approvals
19  Audit
20  Reporting
21  Period Close
22  Intelligence
23  Migration / Cutover
24  Production Hardening
```

**This is the baseline build contract.**

The next implementation documents should be generated directly from this specification rather than starting the architecture again from scratch.
