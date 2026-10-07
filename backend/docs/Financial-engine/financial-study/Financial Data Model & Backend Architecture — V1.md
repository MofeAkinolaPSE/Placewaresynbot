# Synbot Financial Data Model & Backend Architecture — V1

## 1. Architecture Objective

Synbot Finance will replace the client's existing accounting system as the primary financial system of record.

The architecture must therefore provide:

* operational transaction management;
* double-entry accounting;
* General Ledger;
* Accounts Receivable;
* Accounts Payable;
* inventory accounting;
* cash and banking;
* fixed assets;
* budgeting;
* payroll;
* HR/Staff integration;
* tax configuration;
* approvals;
* auditability;
* financial reporting;
* management analytics;
* AI-assisted financial intelligence.

The architecture must be designed around one principle:

> **Operational systems create business events. The accounting engine converts those events into controlled accounting entries. The General Ledger becomes the financial source of truth.**

AI, dashboards and reports consume this information; they do not replace the accounting engine.

---

# 2. Recommended Backend Architecture

The first implementation should use a **modular monolith with clearly separated domains**, rather than immediately splitting the system into many microservices.

Conceptually:

```text
                    SYNBOT FRONTEND
                          │
                          ▼
                  API / APPLICATION LAYER
                          │
        ┌─────────────────┼──────────────────┐
        │                 │                  │
        ▼                 ▼                  ▼
   Business Modules   Accounting Core    Intelligence
        │                 │                  │
        └─────────────────┼──────────────────┘
                          │
                    DATA ACCESS LAYER
                          │
                       PostgreSQL
                          │
                ┌─────────┴─────────┐
                │                   │
          Transaction Data      Audit Data
```

This gives the development team strong domain boundaries without creating unnecessary infrastructure complexity.

The architecture can later extract individual domains into services if scale requires it.

---

# 3. Backend Domain Modules

The backend should be divided into the following logical modules.

```text
core/
├── organization
├── identity
├── master_data
├── sales
├── receivables
├── procurement
├── payables
├── inventory
├── banking
├── accounting
├── fixed_assets
├── payroll
├── hr
├── budgeting
├── tax
├── approvals
├── audit
├── reporting
├── documents
└── intelligence
```

These are **domain boundaries**, not necessarily separate deployed applications.

---

# 4. Core Platform Layer

The platform layer contains functionality used by every financial module.

## Organization

Responsible for:

* organization;
* legal entities;
* branches;
* departments;
* cost centres;
* currencies;
* financial periods.

## Identity & Access

Responsible for:

* users;
* roles;
* permissions;
* entity access;
* branch access;
* approval authority;
* session/security controls.

A user should never receive unrestricted access simply because they belong to the Finance department.

Access should be determined by:

```text
User
 +
Role
 +
Permission
 +
Legal Entity
 +
Branch
 +
Module
```

---

# 5. Master Data Module

The master-data layer owns reusable business definitions.

Core objects:

```text
Account
Account Group
Customer
Supplier
Product
Product Category
Unit of Measure
Batch
Warehouse
Tax Configuration
Price List
Currency
```

The rule is:

> Transaction modules reference master data; they do not duplicate it.

For example, an invoice references a customer ID rather than copying the customer's entire master record into the invoice.

---

# 6. Transaction Architecture

Every major financial transaction should follow a common application pattern:

```text
CREATE
  ↓
VALIDATE
  ↓
SAVE AS DRAFT
  ↓
APPROVE
  ↓
POST
  ↓
ACCOUNT
  ↓
AUDIT
```

Not every transaction needs approval, but every posted transaction must pass validation.

The application should distinguish clearly between:

### Draft data

Can be edited.

### Posted data

Becomes financially authoritative.

### Corrected data

Is corrected through a controlled reversal/correction process rather than silent mutation.

---

# 7. Accounting Engine

The accounting engine is the heart of Synbot Finance.

It should not be embedded inside the sales module, inventory module, payroll module, etc.

Instead:

```text
Sales
       \
Purchasing \
Inventory   \
Payroll      → Accounting Engine → Journal → GL
Banking     /
Assets     /
Expenses  /
```

Every module produces an **accounting event**.

The accounting engine determines the journal entries.

---

# 8. Accounting Event

The `accounting_event` is the bridge between operational activity and accounting.

Example:

```text
Sales Invoice
      ↓
ACCOUNTING_EVENT
      ↓
Accounting Rule
      ↓
Journal Entry
```

An accounting event should contain concepts such as:

* event ID;
* legal entity;
* event type;
* source module;
* source entity;
* source entity ID;
* transaction date;
* posting date;
* financial period;
* currency;
* amount;
* status;
* created by.

Example:

```text
event_type = SALES_INVOICE_POSTED
source_module = SALES
source_entity = sales_invoice
source_id = INV-000492
```

This creates universal traceability.

---

# 9. Accounting Rules Engine

Accounting rules should be configurable rather than hard-coded throughout the application.

Example:

```text
Sales Invoice
      ↓
Revenue Account
Receivable Account
Tax Account
COGS Account
Inventory Account
```

The rule engine determines which accounts are affected.

For a basic sale:

```text
DR Accounts Receivable
CR Sales Revenue

DR Cost of Sales
CR Inventory
```

For a cash sale:

```text
DR Cash/Bank
CR Sales Revenue
```

The application should not allow individual frontend screens to decide these postings.

---

# 10. Journal Engine

The journal engine receives the output of the accounting rules.

Example:

```text
Journal #JE-000923

DR  Accounts Receivable     ₦1,000,000
CR  Sales Revenue           ₦1,000,000
```

For inventory-related accounting:

```text
DR  Cost of Sales           ₦700,000
CR  Inventory               ₦700,000
```

The journal engine validates:

```text
Total Debits = Total Credits
```

before posting.

---

# 11. Journal State Machine

```text
DRAFT
  ↓
VALIDATED
  ↓
APPROVED
  ↓
POSTED
  ↓
REVERSED
```

`POSTED` should be effectively immutable.

A reversal creates another journal entry.

Example:

```text
Original JE
    ↓
Reversal JE
    ↓
Corrected JE
```

This preserves the audit trail.

---

# 12. General Ledger

The GL should be generated from posted journal lines.

Conceptually:

```text
Journal Entry
    │
    └── Journal Lines
            │
            ▼
       General Ledger
```

The GL should contain enough information to identify:

* account;
* date;
* amount;
* debit/credit;
* legal entity;
* branch;
* department;
* cost centre;
* source;
* source transaction;
* journal;
* financial period;
* currency.

This allows reports to be generated dynamically rather than maintaining separate financial copies.

---

# 13. Sales Architecture

Sales should be separated into operational and financial stages.

```text
Customer
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
```

The invoice module owns invoice creation.

The AR module owns the customer's receivable balance.

The accounting engine owns the accounting consequence.

---

# 14. AR Architecture

Core objects:

```text
Customer
Sales Invoice
Credit Note
Customer Payment
Payment Allocation
Customer Ledger
```

The customer's balance should be calculated from authoritative transactions.

Example:

```text
Invoice              +1,000,000
Payment               -600,000
Credit Note           -100,000
--------------------------------
Outstanding            300,000
```

Ageing should be calculated from transaction due dates and settlement status.

---

# 15. Procurement & AP Architecture

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
```

The architecture must allow procurement to operate without forcing every expense through inventory.

Therefore there are two major paths:

```text
Inventory Purchase
        ↓
Inventory
        ↓
AP

Non-inventory Expense
        ↓
Expense Account
        ↓
AP / Payment
```

---

# 16. Inventory Architecture

Inventory should have three distinct layers:

```text
Product Master
      ↓
Inventory Ledger
      ↓
Inventory Balance
```

The balance is derived from movement.

Example:

```text
Opening       100
Purchase      +50
Sale          -20
Adjustment     -5
----------------
Closing       125
```

The system should retain the underlying movements rather than only storing `quantity = 125`.

---

# 17. Batch Architecture

Batch tracking is first-class functionality.

```text
Product
   ↓
Batch
   ↓
Inventory Movement
```

Every relevant movement should identify:

* product;
* batch;
* warehouse;
* quantity;
* unit cost;
* source transaction.

This supports:

* batch traceability;
* recall;
* expiry;
* stock loans;
* returns;
* batch replacement;
* customer-level tracing.

---

# 18. Stock Recall

Recall should operate from the batch.

```text
Batch
 ↓
Inventory Movements
 ↓
Outbound Sales
 ↓
Invoices
 ↓
Customers
```

Therefore a user can query:

> Which customers received batch ABC-123?

and obtain the underlying sales and quantities.

This is a data relationship problem first, not an AI problem.

---

# 19. Stock Loan

Stock loans must be represented independently from sales.

```text
Stock Loan
 ├── Original Product
 ├── Original Batch
 ├── Quantity
 ├── Customer
 ├── Loan Date
 ├── Expected Return
 └── Status
```

A stock loan should not create sales revenue or an ordinary customer receivable.

When returned:

```text
Loan
 ↓
Return
 ↓
Returned Batch
 ↓
Inventory
```

The returned batch may differ from the original batch, so both batch identities must be retained.

---

# 20. Banking Architecture

Banking should connect to accounting but remain independently identifiable.

```text
Bank Account
     ↓
Bank Transaction
     ↓
Accounting Event
     ↓
Journal
     ↓
GL
```

Bank reconciliation operates separately:

```text
Bank Statement
      ↓
Statement Transactions
      ↓
Matching Engine
      ↓
Reconciliation
```

The system should support:

```text
MATCHED
LIKELY_MATCH
UNMATCHED
DUPLICATE
EXCEPTION
```

---

# 21. Cash Architecture

Cash should distinguish physical cash from bank money.

```text
Cash Account
Bank Account
```

Example:

```text
Cash on Hand
     ↓
Bank Lodgement
     ↓
Bank Account
```

Accounting:

```text
DR Bank
CR Cash
```

This must automatically flow into the GL.

---

# 22. Fixed Asset Architecture

Fixed assets should operate independently from ordinary expenses.

```text
Acquisition
   ↓
Asset Register
   ↓
Capitalisation
   ↓
Depreciation
   ↓
Disposal
```

The depreciation engine creates accounting events.

For example:

```text
DR Depreciation Expense
CR Accumulated Depreciation
```

The exact depreciation policy will be finalized after the accounting-policy research stage.

---

# 23. Payroll Architecture

Payroll is a core financial module.

```text
HR
 │
 ├── Employee
 ├── Employment
 ├── Compensation
 ├── Attendance
 └── Leave
       │
       ▼
    Payroll
       │
       ├── Earnings
       ├── Allowances
       ├── Deductions
       ├── Statutory
       └── Net Pay
             │
             ▼
        Payroll Journal
             │
             ▼
             GL
```

The HR dashboard remains the operational home for employee information.

Finance consumes the payroll result.

---

# 24. Payroll Separation

Payroll should have three separate concepts:

### HR data

Who the employee is.

### Payroll calculation

What the employee should receive.

### Payroll payment

What was actually paid.

Therefore:

```text
Employee
    ↓
Payroll Run
    ↓
Payroll Result
    ↓
Payroll Journal
    ↓
Payment
```

This distinction is essential for reconciliation.

---

# 25. Budget Architecture

Budgeting should sit above the GL rather than creating a parallel accounting system.

```text
Budget
    +
Actual GL
    ↓
Variance Engine
```

Budget dimensions should support:

* account;
* period;
* department;
* branch;
* cost centre;
* legal entity.

This enables:

```text
Budget
vs
Actual
vs
Variance
```

---

# 26. Reporting Architecture

Reports should be generated from authoritative accounting data.

```text
                  GENERAL LEDGER
                        │
             ┌──────────┼──────────┐
             ▼          ▼          ▼
         Trial       Account     Journal
         Balance     Ledger      Reports
             │
       ┌─────┼──────────┐
       ▼     ▼          ▼
      P&L  Balance    Cash Flow
           Sheet
```

Specialized reports consume their relevant sub-ledgers:

```text
AR → Aged Receivables
AP → Aged Payables
Inventory → Stock Reports
Payroll → Payroll Reports
Banking → Reconciliation Reports
Assets → Fixed Asset Reports
```

---

# 27. Reporting Drill-Down

Every major financial report should support drill-down.

Example:

```text
Income Statement
      ↓
Sales Revenue
      ↓
GL Account
      ↓
Journal Entry
      ↓
Sales Invoice
      ↓
Customer
      ↓
Invoice Lines
      ↓
Product / Batch
```

This is one of the defining capabilities of Synbot.

---

# 28. API Architecture

The API should be domain-oriented.

Example:

```text
/api/v1/organizations
/api/v1/entities
/api/v1/customers
/api/v1/suppliers
/api/v1/products
/api/v1/inventory
/api/v1/sales
/api/v1/receivables
/api/v1/procurement
/api/v1/payables
/api/v1/banking
/api/v1/accounting
/api/v1/assets
/api/v1/hr
/api/v1/payroll
/api/v1/budgets
/api/v1/reports
/api/v1/audit
```

The exact framework can follow the existing Synbot backend conventions, but FastAPI is a natural fit for the current architecture.

---

# 29. Important API Principle

The frontend should never directly create journal entries for ordinary business transactions.

For example:

Bad:

```text
Frontend
 ↓
POST /journal-entry
```

for every sales invoice.

Correct:

```text
Frontend
 ↓
POST /sales/invoices
 ↓
Sales Service
 ↓
Validation
 ↓
Accounting Event
 ↓
Accounting Engine
 ↓
Journal
 ↓
GL
```

Direct journal entry APIs should exist only for controlled accounting operations.

---

# 30. Transaction Posting Service

A centralized posting service should be introduced.

Conceptually:

```text
PostingService
    │
    ├── validate()
    ├── resolve_accounts()
    ├── build_journal()
    ├── validate_balance()
    ├── post()
    └── audit()
```

Every accounting-producing module calls this service.

This prevents different modules from implementing different accounting logic.

---

# 31. Control Engine

Before posting:

```text
Transaction
     ↓
Control Engine
```

Checks may include:

* entity exists;
* account exists;
* account is active;
* financial period is open;
* debit equals credit;
* required approval exists;
* duplicate transaction check;
* credit limit;
* sufficient stock;
* valid batch;
* valid tax configuration;
* valid currency;
* required document;
* user has authority.

Only after successful validation:

```text
POST
```

---

# 32. Audit Engine

The audit engine should receive events from the application layer.

Example:

```text
User
 ↓
Create Invoice
 ↓
Audit Event

Manager
 ↓
Approve Invoice
 ↓
Audit Event

Accounting Engine
 ↓
Post Journal
 ↓
Audit Event
```

Audit should therefore capture both:

* business actions;
* accounting actions.

---

# 33. Document Architecture

Documents should be stored independently from transactional records.

```text
Transaction
     │
     └── Document Reference
              │
              ▼
        Document Storage
```

The database should store metadata and references rather than unnecessarily embedding large files into transactional tables.

---

# 34. AI / Intelligence Layer

The AI layer sits above the financial data.

```text
User
 ↓
Finance AI
 ↓
Intent Detection
 ↓
Financial Query
 ↓
Reporting / Query Layer
 ↓
Authoritative Data
 ↓
Response
```

Examples:

> What are our outstanding receivables?

> Which customers are overdue?

> What caused the increase in expenses this month?

> Which products had the largest stock adjustments?

> What is our current cash position?

The AI should retrieve and calculate from actual system data.

---

# 35. AI Write Restrictions

The Finance AI should initially be **read-only for financial records**.

It can:

* query;
* summarize;
* explain;
* compare;
* identify anomalies;
* generate reports;
* recommend actions.

It should not independently:

* post journals;
* change account balances;
* approve payments;
* modify payroll;
* alter invoices;
* delete transactions.

Any future AI-assisted financial action should pass through the same application APIs, permissions, validation and approval system as a human user.

---

# 36. Database Strategy

PostgreSQL should be the primary transactional database.

The initial architecture should favour a **single database with strong logical domain separation**.

Conceptually:

```text
PostgreSQL
│
├── organization
├── identity
├── master_data
├── sales
├── receivables
├── procurement
├── payables
├── inventory
├── banking
├── accounting
├── assets
├── hr
├── payroll
├── budgeting
├── tax
├── approvals
├── audit
└── documents
```

Whether these become PostgreSQL schemas or remain logically separated through table naming/module boundaries should be decided during implementation.

The important requirement is domain ownership.

---

# 37. Tenant Isolation

Because Synbot is intended to evolve into a multi-company platform, almost every business record should be traceable to a legal entity.

At minimum:

```text
organization_id
legal_entity_id
```

should propagate through relevant financial records.

Where applicable:

```text
branch_id
department_id
cost_centre_id
```

should also be available.

This prevents a future redesign when the first client expands to multiple subsidiaries.

---

# 38. Transaction IDs

Every major transaction should have two identifiers:

### Internal ID

A UUID or equivalent immutable technical identifier.

### Human-readable number

Examples:

```text
INV-2026-000492
PO-2026-000183
PAY-2026-000092
JE-2026-001923
AST-2026-000034
PR-2026-000011
```

The human-readable number is for users.

The internal ID is for relationships.

---

# 39. Financial Period Control

Every accounting transaction must resolve to a financial period.

```text
Transaction Date
      ↓
Financial Period
      ↓
Period Status
```

If:

```text
period.status = CLOSED
```

posting must fail unless a controlled reopening process is used.

---

# 40. Concurrency & Idempotency

Financial systems must protect against duplicate posting.

For example, if a payment request is submitted twice because of a network retry:

```text
Request A → Payment
Request B → Payment
```

the system must not accidentally create two payments.

Financial APIs should therefore use:

* unique transaction references;
* idempotency keys where appropriate;
* database constraints;
* transactional database operations.

---

# 41. Database Transaction Boundary

Posting should be atomic.

Example:

```text
BEGIN TRANSACTION

Create accounting event
Create journal
Create journal lines
Validate debit/credit
Update relevant ledger state
Create audit event

COMMIT
```

If any critical stage fails:

```text
ROLLBACK
```

No partially posted financial transaction should remain.

---

# 42. Event Architecture

The first version does not need a complicated distributed event bus.

However, the domain model should be event-oriented.

Example:

```text
SALES_INVOICE_POSTED
PAYMENT_RECEIVED
INVENTORY_ADJUSTED
PURCHASE_RECEIVED
PAYROLL_POSTED
ASSET_DEPRECIATED
BANK_TRANSACTION_RECONCILED
```

These events can later feed:

* notifications;
* analytics;
* AI;
* anomaly detection;
* dashboards;
* external integrations.

---

# 43. Caching

Caching can be introduced for read-heavy dashboard information.

Examples:

* dashboard KPIs;
* ageing summaries;
* inventory summaries;
* frequently requested reports.

But cached values must never become the accounting source of truth.

```text
PostgreSQL
    ↓
Reporting/Query Layer
    ↓
Cache
    ↓
Dashboard
```

not:

```text
Dashboard
 ↓
Cache
 ↓
Accounting Truth
```

---

# 44. Search & AI Retrieval

A separate search/vector layer may eventually be used for:

* documents;
* policies;
* financial explanations;
* transaction descriptions;
* supporting documents;
* natural-language retrieval.

However:

> **Vector search must never replace relational financial queries.**

For:

> "What is the outstanding balance for customer X?"

use the relational financial data.

For:

> "Explain our credit policy."

RAG/vector retrieval is appropriate.

---

# 45. Backend Service Boundaries

The first production architecture should therefore look approximately like:

```text
                FastAPI Application
                        │
 ┌──────────────────────┼───────────────────────┐
 │                      │                       │
Domain Services    Accounting Core       Query/Reporting
 │                      │                       │
 │                Posting Engine               │
 │                Journal Engine               │
 │                Control Engine               │
 │                      │                       │
 └──────────────────────┼───────────────────────┘
                        │
                    PostgreSQL
                        │
              ┌─────────┴─────────┐
              │                   │
          File Storage        Cache/Search
```

---

# 46. Suggested Internal Backend Structure

A practical implementation could use:

```text
backend/
│
├── app/
│   ├── api/
│   │   └── v1/
│   │
│   ├── core/
│   │   ├── config/
│   │   ├── security/
│   │   └── database/
│   │
│   ├── domains/
│   │   ├── organization/
│   │   ├── customers/
│   │   ├── suppliers/
│   │   ├── products/
│   │   ├── sales/
│   │   ├── receivables/
│   │   ├── procurement/
│   │   ├── payables/
│   │   ├── inventory/
│   │   ├── banking/
│   │   ├── accounting/
│   │   ├── assets/
│   │   ├── hr/
│   │   ├── payroll/
│   │   ├── budgeting/
│   │   ├── tax/
│   │   ├── approvals/
│   │   └── audit/
│   │
│   ├── reporting/
│   ├── intelligence/
│   └── shared/
│
├── migrations/
├── tests/
└── scripts/
```

The exact folder names can change. The domain separation should not.

---

# 47. Development Sequence

The development engine should **not attempt to build everything simultaneously**.

Recommended order:

## Phase 1 — Foundation

Build:

```text
Organization
Legal Entity
Branch
Department
Cost Centre
Users
Roles
Permissions
Financial Periods
Currency
```

## Phase 2 — Financial Master Data

Build:

```text
Chart of Accounts
Customers
Suppliers
Products
Categories
Units
Warehouses
Tax Configuration
```

## Phase 3 — Accounting Core

Build:

```text
Accounting Events
Accounting Rules
Journal Entries
Journal Lines
Posting Engine
General Ledger
Period Controls
Reversal Engine
```

This is the most important technical phase.

## Phase 4 — Sales & AR

Build:

```text
Sales Orders
Deliveries
Invoices
Credit Notes
Customer Payments
Payment Allocation
AR Ledger
Ageing
```

## Phase 5 — Procurement & AP

Build:

```text
Purchase Requests
Purchase Orders
Goods Receipts
Supplier Invoices
Supplier Payments
AP Ledger
Ageing
```

## Phase 6 — Inventory

Build:

```text
Inventory Ledger
Batches
Stock Movements
Adjustments
Transfers
Returns
Loans
Recall
Stock Counts
```

## Phase 7 — Banking

Build:

```text
Bank Accounts
Cash
Bank Transactions
Statements
Reconciliation
```

## Phase 8 — Fixed Assets

Build:

```text
Asset Register
Capitalisation
Depreciation
Disposal
```

## Phase 9 — HR & Payroll

Build:

```text
Employee
Employment
Compensation
Attendance
Leave
Payroll
Payroll Journal
Payroll Payment
Staff Loans
```

## Phase 10 — Budgeting & Tax

Build:

```text
Budgets
Variance
Tax Engine
Tax Reports
```

## Phase 11 — Reporting

Build:

```text
Trial Balance
P&L
Balance Sheet
Cash Flow
GL
AR
AP
Inventory
Bank
Payroll
Asset
Budget
Management Reports
```

## Phase 12 — Intelligence

Finally:

```text
Finance AI
Anomaly Detection
Forecasting
Natural Language Queries
Executive Finance Dashboard
```

---

# 48. Critical Development Rule

The team should not begin by building the dashboard.

The correct dependency is:

```text
DATA MODEL
     ↓
ACCOUNTING ENGINE
     ↓
TRANSACTION MODULES
     ↓
REPORTING
     ↓
DASHBOARDS
     ↓
AI
```

Building the UI first would create a visually impressive system without a reliable accounting foundation.

---

# 49. Definition of Done for the Accounting Core

Before declaring the accounting engine production-ready, it must demonstrate:

```text
✓ Double-entry enforcement
✓ Balanced journals
✓ Immutable posted entries
✓ Reversal capability
✓ Open/closed periods
✓ Account validation
✓ Legal-entity isolation
✓ Audit trail
✓ Source transaction traceability
✓ Idempotent posting
✓ Transaction rollback
✓ Journal-to-GL consistency
✓ GL-to-report consistency
```

The accounting engine is the foundation upon which every other financial module depends.

---

# 50. Final Architecture

The resulting Synbot Financial Operating System can be represented as:

```text
                         SYNBOT
                           │
                 ┌─────────┴─────────┐
                 │                   │
             OPERATIONS          MANAGEMENT
                 │                   │
       ┌─────────┼─────────┐         │
       │         │         │         │
     Sales    Purchase   HR/Payroll  Dashboards
       │         │         │         │
       └─────────┼─────────┘         │
                 │                   │
             INVENTORY               │
                 │                   │
                 └───────┬───────────┘
                         │
                 ACCOUNTING ENGINE
                         │
             ┌───────────┼───────────┐
             │           │           │
          Journals       GL       Controls
             │           │           │
             └───────────┼───────────┘
                         │
                   FINANCIAL DATA
                         │
       ┌─────────────────┼─────────────────┐
       │                 │                 │
    Reporting        Analytics          AI/RAG
       │                 │                 │
       └─────────────────┼─────────────────┘
                         │
                  EXECUTIVE INSIGHT
```

The architectural objective is therefore not to reproduce Sage screen-for-screen.

It is to create a **native Synbot financial operating system**, where operational activity, accounting, inventory, payroll, controls and intelligence all operate from one connected financial data model.

# End of V1
