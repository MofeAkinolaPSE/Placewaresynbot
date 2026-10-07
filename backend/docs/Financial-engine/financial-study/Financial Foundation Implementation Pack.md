# Synbot Financial Foundation Implementation Pack

**Version:** 1.0
**Build Target:** Foundation Sprint
**Architecture:** FastAPI + PostgreSQL + React/TypeScript
**Status:** Ready for engineering implementation

---

# 1. Foundation Objective

The Foundation release establishes the infrastructure on which every future financial module depends.

It must deliver:

* organization hierarchy;
* authentication/authorization foundation;
* financial periods;
* currencies;
* chart of accounts;
* accounting events;
* journals;
* journal lines;
* posting engine;
* general ledger;
* trial balance;
* audit trail;
* API foundation;
* React application shell;
* Finance dashboard foundation;
* golden accounting tests.

The Foundation is **not** yet the full ERP.

The first objective is proving:

> A valid financial event can become a balanced, auditable journal entry and appear correctly in the General Ledger and Trial Balance.

---

# 2. Technology Baseline

## Backend

```text
Python
FastAPI
SQLAlchemy
Alembic
Pydantic
PostgreSQL
pytest
```

Optional infrastructure:

```text
Redis
Background Worker
Object Storage
```

Do not introduce these unless required by the implementation.

## Frontend

```text
React
TypeScript
Vite
React Router
```

Use a component system already standardized by the Synbot frontend stack where available.

---

# 3. Initial Repository

```text
synbot-financial/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── dependencies.py
│   │   │
│   │   ├── core/
│   │   │   ├── database.py
│   │   │   ├── security.py
│   │   │   ├── exceptions.py
│   │   │   ├── middleware.py
│   │   │   └── logging.py
│   │   │
│   │   ├── organization/
│   │   ├── identity/
│   │   ├── master_data/
│   │   └── accounting/
│   │
│   ├── migrations/
│   └── tests/
│
├── frontend/
│   └── src/
│       ├── app/
│       ├── components/
│       ├── layouts/
│       ├── modules/
│       │   ├── dashboard/
│       │   └── finance/
│       ├── services/
│       ├── hooks/
│       ├── routes/
│       └── types/
│
├── docs/
├── docker-compose.yml
├── .env.example
└── README.md
```

---

# 4. Database Schema

The first migration should establish the organizational foundation.

## organizations

```sql
CREATE TABLE organizations (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL UNIQUE,
    base_currency_id UUID,
    status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

# 5. Legal Entities

```sql
CREATE TABLE legal_entities (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL,
    registration_number VARCHAR(100),
    tax_identifier VARCHAR(100),
    base_currency_id UUID,
    fiscal_year_start SMALLINT NOT NULL DEFAULT 1,
    status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (organization_id, code)
);
```

A legal entity is the accounting boundary.

---

# 6. Branches

```sql
CREATE TABLE branches (
    id UUID PRIMARY KEY,
    legal_entity_id UUID NOT NULL REFERENCES legal_entities(id),
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (legal_entity_id, code)
);
```

---

# 7. Departments

```sql
CREATE TABLE departments (
    id UUID PRIMARY KEY,
    legal_entity_id UUID NOT NULL REFERENCES legal_entities(id),
    branch_id UUID REFERENCES branches(id),
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',

    UNIQUE (legal_entity_id, code)
);
```

---

# 8. Cost Centres

```sql
CREATE TABLE cost_centres (
    id UUID PRIMARY KEY,
    legal_entity_id UUID NOT NULL REFERENCES legal_entities(id),
    department_id UUID REFERENCES departments(id),
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',

    UNIQUE (legal_entity_id, code)
);
```

---

# 9. Currencies

```sql
CREATE TABLE currencies (
    id UUID PRIMARY KEY,
    code CHAR(3) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    symbol VARCHAR(10),
    decimal_places SMALLINT NOT NULL DEFAULT 2,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);
```

The initial implementation should support NGN cleanly.

Multi-currency architecture should exist, but complex FX accounting should not be implemented until required.

---

# 10. Financial Periods

```sql
CREATE TABLE financial_periods (
    id UUID PRIMARY KEY,
    legal_entity_id UUID NOT NULL
        REFERENCES legal_entities(id),

    name VARCHAR(100) NOT NULL,
    period_number SMALLINT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,

    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ,
    closed_by UUID,

    CHECK (end_date >= start_date),
    UNIQUE (legal_entity_id, start_date, end_date)
);
```

Valid statuses:

```text
OPEN
CLOSING
CLOSED
```

---

# 11. Account Groups

```sql
CREATE TABLE account_groups (
    id UUID PRIMARY KEY,
    legal_entity_id UUID NOT NULL
        REFERENCES legal_entities(id),

    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL,

    account_type VARCHAR(30) NOT NULL,

    parent_id UUID REFERENCES account_groups(id),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (legal_entity_id, code)
);
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

# 12. Accounts

```sql
CREATE TABLE accounts (
    id UUID PRIMARY KEY,

    legal_entity_id UUID NOT NULL
        REFERENCES legal_entities(id),

    account_group_id UUID
        REFERENCES account_groups(id),

    code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,

    account_type VARCHAR(30) NOT NULL,
    normal_balance VARCHAR(10) NOT NULL,

    is_control_account BOOLEAN NOT NULL DEFAULT FALSE,
    is_postable BOOLEAN NOT NULL DEFAULT TRUE,

    parent_id UUID REFERENCES accounts(id),

    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (legal_entity_id, code)
);
```

Normal balance:

```text
DEBIT
CREDIT
```

---

# 13. Account Rules

An account should not be deleted once it has financial history.

Instead:

```text
ACTIVE → INACTIVE
```

An inactive account cannot receive new postings.

A non-postable parent account cannot receive direct journal lines.

---

# 14. Accounting Events

```sql
CREATE TABLE accounting_events (
    id UUID PRIMARY KEY,

    organization_id UUID NOT NULL
        REFERENCES organizations(id),

    legal_entity_id UUID NOT NULL
        REFERENCES legal_entities(id),

    financial_period_id UUID NOT NULL
        REFERENCES financial_periods(id),

    event_type VARCHAR(100) NOT NULL,

    source_type VARCHAR(100),
    source_id UUID,

    event_date DATE NOT NULL,

    currency_id UUID NOT NULL
        REFERENCES currencies(id),

    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',

    metadata JSONB NOT NULL DEFAULT '{}',

    idempotency_key VARCHAR(255),

    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    posted_at TIMESTAMPTZ,

    UNIQUE (legal_entity_id, idempotency_key)
);
```

This becomes the bridge between operational events and accounting.

---

# 15. Journal Entries

```sql
CREATE TABLE journal_entries (
    id UUID PRIMARY KEY,

    organization_id UUID NOT NULL
        REFERENCES organizations(id),

    legal_entity_id UUID NOT NULL
        REFERENCES legal_entities(id),

    financial_period_id UUID NOT NULL
        REFERENCES financial_periods(id),

    accounting_event_id UUID
        REFERENCES accounting_events(id),

    journal_number VARCHAR(100) NOT NULL,

    entry_date DATE NOT NULL,

    description TEXT,

    status VARCHAR(30) NOT NULL DEFAULT 'DRAFT',

    reversal_of_id UUID
        REFERENCES journal_entries(id),

    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    approved_by UUID,
    approved_at TIMESTAMPTZ,

    posted_by UUID,
    posted_at TIMESTAMPTZ,

    UNIQUE (legal_entity_id, journal_number)
);
```

---

# 16. Journal Lines

```sql
CREATE TABLE journal_lines (
    id UUID PRIMARY KEY,

    journal_entry_id UUID NOT NULL
        REFERENCES journal_entries(id)
        ON DELETE RESTRICT,

    account_id UUID NOT NULL
        REFERENCES accounts(id),

    department_id UUID
        REFERENCES departments(id),

    branch_id UUID
        REFERENCES branches(id),

    cost_centre_id UUID
        REFERENCES cost_centres(id),

    description TEXT,

    debit NUMERIC(20,2) NOT NULL DEFAULT 0,
    credit NUMERIC(20,2) NOT NULL DEFAULT 0,

    currency_id UUID NOT NULL
        REFERENCES currencies(id),

    exchange_rate NUMERIC(20,8) NOT NULL DEFAULT 1,
    base_debit NUMERIC(20,2) NOT NULL DEFAULT 0,
    base_credit NUMERIC(20,2) NOT NULL DEFAULT 0,

    CHECK (
        (debit > 0 AND credit = 0)
        OR
        (credit > 0 AND debit = 0)
        OR
        (debit = 0 AND credit = 0)
    )
);
```

The application layer must additionally prevent zero-value lines where inappropriate.

---

# 17. Journal Balance Constraint

A journal cannot be posted unless:

```text
SUM(base_debit)
=
SUM(base_credit)
```

This should be checked inside the posting transaction.

Do not rely exclusively on frontend validation.

---

# 18. Audit Events

```sql
CREATE TABLE audit_events (
    id UUID PRIMARY KEY,

    organization_id UUID
        REFERENCES organizations(id),

    legal_entity_id UUID
        REFERENCES legal_entities(id),

    actor_id UUID,

    action VARCHAR(100) NOT NULL,

    entity_type VARCHAR(100),
    entity_id UUID,

    before_state JSONB,
    after_state JSONB,

    metadata JSONB NOT NULL DEFAULT '{}',

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Audit records are append-only.

---

# 19. Initial Indexes

Create indexes for:

```text
financial_periods.legal_entity_id
accounts.legal_entity_id
journal_entries.legal_entity_id
journal_entries.entry_date
journal_entries.status
journal_lines.journal_entry_id
journal_lines.account_id
accounting_events.source_type + source_id
audit_events.entity_type + entity_id
```

The GL will depend heavily on:

```text
account_id
entry_date
legal_entity_id
```

so those indexes are particularly important.

---

# 20. Backend Models

Each SQLAlchemy model should correspond closely to the database.

Example:

```python
class Account(Base):
    __tablename__ = "accounts"

    id = mapped_column(UUID, primary_key=True)
    legal_entity_id = mapped_column(
        ForeignKey("legal_entities.id"),
        nullable=False
    )

    code = mapped_column(String(50), nullable=False)
    name = mapped_column(String(255), nullable=False)

    account_type = mapped_column(String(30), nullable=False)
    normal_balance = mapped_column(String(10), nullable=False)

    is_control_account = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    is_postable = mapped_column(
        Boolean,
        default=True,
        nullable=False
    )

    status = mapped_column(
        String(20),
        default="ACTIVE",
        nullable=False
    )
```

Do not put business posting logic inside the model.

---

# 21. Pydantic Schemas

Separate:

```text
Create
Update
Read
List
Command
```

Example:

```python
class AccountCreate(BaseModel):
    code: str
    name: str
    account_type: AccountType
    normal_balance: NormalBalance
    account_group_id: UUID | None = None
    is_postable: bool = True
```

---

# 22. Account Service

```python
class AccountService:

    def create(...)
    def update(...)
    def deactivate(...)
    def get(...)
    def list(...)
    def validate_postable(...)
```

Important:

```text
deactivate()
```

rather than:

```text
delete()
```

for accounts with financial history.

---

# 23. Financial Period Service

```python
class FinancialPeriodService:

    def create(...)
    def open(...)
    def begin_close(...)
    def close(...)
    def validate_open(...)
```

Every posting operation calls:

```python
financial_period_service.validate_open(...)
```

before creating a journal.

---

# 24. PostingService

This is the critical implementation.

```python
class PostingService:

    def post(
        self,
        event: AccountingEventRequest,
        db: Session
    ) -> JournalEntry:

        self.validate_event(event)
        self.validate_period(event)
        self.validate_scope(event)

        journal = self.build_journal(event)

        self.validate_accounts(journal)
        self.validate_balance(journal)

        self.persist(journal)
        self.mark_posted(event)
        self.create_audit_event(event, journal)

        return journal
```

The actual implementation must execute within one database transaction.

---

# 25. Posting Algorithm

```text
RECEIVE EVENT
     ↓
CHECK IDEMPOTENCY
     ↓
CHECK ENTITY SCOPE
     ↓
CHECK FINANCIAL PERIOD
     ↓
RESOLVE ACCOUNTING RULE
     ↓
BUILD JOURNAL
     ↓
VALIDATE ACCOUNTS
     ↓
VALIDATE DEBIT/CREDIT
     ↓
CREATE JOURNAL
     ↓
POST
     ↓
AUDIT
     ↓
COMMIT
```

Any failure:

```text
ROLLBACK
```

---

# 26. Journal Service

```python
class JournalService:

    def create(...)
    def validate(...)
    def approve(...)
    def post(...)
    def reverse(...)
    def get(...)
```

Manual journals and system-generated journals should ultimately use the same posting infrastructure.

---

# 27. General Ledger

Do not create a second mutable GL table initially.

The GL should be derived from:

```text
POSTED journal_entries
+
journal_lines
```

Conceptually:

```sql
SELECT
    jl.account_id,
    je.entry_date,
    je.journal_number,
    jl.description,
    jl.debit,
    jl.credit
FROM journal_lines jl
JOIN journal_entries je
    ON je.id = jl.journal_entry_id
WHERE je.status = 'POSTED';
```

This keeps the financial source of truth simple.

---

# 28. GL Account Balance

For an account:

```text
Opening Balance
+
Debits
-
Credits
=
Closing Balance
```

The exact sign presentation depends on account normal balance.

The reporting service should handle presentation rather than embedding presentation assumptions in the ledger.

---

# 29. Trial Balance

Trial Balance must calculate:

```text
Account
Opening
Debit
Credit
Closing
```

and prove:

```text
Total Debits = Total Credits
```

The client's existing Trial Balance is a useful migration validation point; the supplied legacy report contains 167 account rows as of June 2026.

---

# 30. Initial Accounting API

Base:

```text
/api/v1
```

## Organization

```http
GET  /organizations
POST /organizations

GET  /legal-entities
POST /legal-entities

GET  /branches
POST /branches

GET  /departments
POST /departments

GET  /cost-centres
POST /cost-centres
```

---

# 31. Financial Period API

```http
GET  /financial-periods
POST /financial-periods

POST /financial-periods/{id}/open
POST /financial-periods/{id}/begin-close
POST /financial-periods/{id}/close
```

Close must execute validation controls.

---

# 32. Chart of Accounts API

```http
GET  /accounts
POST /accounts

GET  /accounts/{id}
PATCH /accounts/{id}

POST /accounts/{id}/deactivate
```

Do not expose:

```http
DELETE /accounts/{id}
```

as a normal operation.

---

# 33. Journal API

```http
GET  /journals
POST /journals

GET  /journals/{id}

POST /journals/{id}/validate
POST /journals/{id}/approve
POST /journals/{id}/post
POST /journals/{id}/reverse
```

---

# 34. GL API

```http
GET /general-ledger
GET /general-ledger/accounts/{account_id}
GET /general-ledger/accounts/{account_id}/summary

GET /trial-balance
```

Filters:

```text
date_from
date_to
account
branch
department
cost_centre
journal
```

---

# 35. Audit API

Audit is read-only:

```http
GET /audit-events
GET /audit-events/{id}
GET /audit-events/entity/{entity_type}/{entity_id}
```

No frontend endpoint should allow deletion.

---

# 36. Error Contract

Every error should follow:

```json
{
  "error": {
    "code": "PERIOD_CLOSED",
    "message": "The selected financial period is closed.",
    "details": {},
    "request_id": "..."
  }
}
```

Initial errors:

```text
PERMISSION_DENIED
RESOURCE_NOT_FOUND
VALIDATION_FAILED
DUPLICATE_RESOURCE
PERIOD_CLOSED
ACCOUNT_INACTIVE
ACCOUNT_NOT_POSTABLE
UNBALANCED_JOURNAL
INVALID_STATE_TRANSITION
IDEMPOTENCY_CONFLICT
```

---

# 37. Finance Frontend Foundation

Initial routes:

```text
/
 /dashboard

/finance
/finance/accounts
/finance/accounts/:id
/finance/journals
/finance/journals/:id
/finance/general-ledger
/finance/trial-balance
/finance/periods
/finance/audit
```

---

# 38. Application Shell

```text
┌──────────────────────────────────────────────────┐
│ SYNBOT │ Company ▼ │ Search │ Alerts │ User ▼   │
├───────────────┬──────────────────────────────────┤
│ Dashboard     │                                  │
│ Finance       │                                  │
│ Sales         │          Workspace               │
│ Procurement   │                                  │
│ Inventory     │                                  │
│ Banking       │                                  │
│ HR & Payroll  │                                  │
│ Reports       │                                  │
│ Intelligence  │                                  │
│ Admin         │                                  │
└───────────────┴──────────────────────────────────┘
```

Only Foundation modules need to be functional initially.

---

# 39. Finance Dashboard V1

Display:

```text
Cash
AR
AP
Revenue
Expenses
Net Profit
```

and:

```text
Current Period
Trial Balance Status
Open Approvals
Exceptions
```

Do not manufacture sophisticated analytics yet.

---

# 40. Chart of Accounts Screen

Features:

* search;
* account type filter;
* active/inactive;
* account hierarchy;
* create account;
* edit;
* deactivate;
* view account activity.

Example:

```text
1000  ASSETS
  1100  Cash
  1200  Bank
  1300  Accounts Receivable
  1400  Inventory

2000  LIABILITIES
...
```

The exact account hierarchy will come from the approved client COA/migration process rather than being invented by the frontend agent.

---

# 41. Journal Screen

Columns:

```text
Journal #
Date
Description
Status
Debit
Credit
Created By
```

Journal detail:

```text
Header
↓
Lines
↓
Totals
↓
Approval
↓
Audit
```

---

# 42. Journal Creation UX

```text
Date
Description

Account       Debit       Credit
----------------------------------
Cash          100,000
Revenue                    100,000

Total         100,000     100,000

[Validate]
[Save Draft]
[Submit]
```

The frontend should immediately show:

```text
✓ Journal balanced
```

or:

```text
✕ Journal is out of balance by ₦X
```

But backend validation remains authoritative.

---

# 43. Trial Balance Screen

```text
Account | Opening | Debit | Credit | Closing
```

Top-level status:

```text
✓ Balanced
```

or:

```text
⚠ Difference detected
```

Clicking an account opens its GL.

---

# 44. GL Screen

```text
Account: 1100 Cash

Date       Journal     Description     Debit    Credit    Balance
------------------------------------------------------------------
...
```

Clicking the journal opens the source transaction.

---

# 45. Audit Screen

Filters:

```text
Date
User
Action
Entity
Entity ID
```

Timeline:

```text
10:32  Mofe created journal
10:34  Finance Manager approved
10:35  Journal posted
10:35  Audit event created
```

---

# 46. Foundation API Client

Frontend should have a central client:

```text
services/
├── apiClient.ts
├── authService.ts
├── organizationService.ts
├── accountService.ts
├── journalService.ts
├── ledgerService.ts
└── auditService.ts
```

Do not scatter raw `fetch()` calls across components.

---

# 47. Frontend State

Keep server state separate from UI state.

Server state:

* accounts;
* journals;
* GL;
* trial balance;
* periods.

UI state:

* filters;
* modal visibility;
* selected rows;
* form state.

Do not duplicate authoritative backend financial state unnecessarily.

---

# 48. Golden Test 001 — Manual Journal

Input:

```text
DR Cash       ₦100,000
CR Revenue    ₦100,000
```

Expected:

```text
Journal = POSTED
Debits = ₦100,000
Credits = ₦100,000
GL updated
Trial Balance updated
Audit event created
```

---

# 49. Golden Test 002 — Unbalanced Journal

Input:

```text
DR Cash       ₦100,000
CR Revenue     ₦90,000
```

Expected:

```text
UNBALANCED_JOURNAL
```

No journal posting.

No GL mutation.

No audit event claiming a successful post.

---

# 50. Golden Test 003 — Closed Period

Attempt:

```text
Post journal
```

against:

```text
Period = CLOSED
```

Expected:

```text
PERIOD_CLOSED
```

No financial mutation.

---

# 51. Golden Test 004 — Inactive Account

Attempt to post:

```text
DR inactive account
```

Expected:

```text
ACCOUNT_INACTIVE
```

No posting.

---

# 52. Golden Test 005 — Duplicate Request

Send the same financial request twice with the same:

```text
Idempotency-Key
```

Expected:

```text
First request → POSTED
Second request → existing result / controlled idempotency response
```

Never two journals.

---

# 53. Golden Test 006 — Reversal

Given:

```text
Original Journal
```

create:

```text
Reversal Journal
```

The original must remain intact.

The reversal references:

```text
reversal_of_id
```

---

# 54. Golden Test 007 — GL Integrity

After a set of posted journals:

```text
SUM(all posted debits)
=
SUM(all posted credits)
```

If not:

```text
FAIL TEST
```

---

# 55. Golden Test 008 — Trial Balance

Trial balance must satisfy:

```text
Total Debit
=
Total Credit
```

for every tested legal entity and period.

---

# 56. Golden Test 009 — Entity Isolation

Create:

```text
Company A
Company B
```

Create an account in A.

Attempt to access it using B context.

Expected:

```text
RESOURCE_NOT_FOUND
```

or equivalent secure isolation response.

Never expose Company A's record.

---

# 57. Golden Test 010 — Audit

Perform:

```text
Create Account
Deactivate Account
Create Journal
Approve Journal
Post Journal
Reverse Journal
```

Expected audit trail:

```text
CREATE
DEACTIVATE
CREATE
APPROVE
POST
REVERSE
```

in chronological order.

---

# 58. Migration Seed Strategy

Once Foundation is working, the client's 465-account legacy COA can be imported into a controlled staging process rather than manually entering hundreds of accounts.

The migration process should generate:

```text
legacy_account_code
legacy_account_name
synbot_account_id
mapping_status
mapping_reason
approved_by
approved_at
```

No automatic mapping should silently become production accounting policy.

---

# 59. Historical Validation Baseline

Use 30 June 2026 as the first major reconciliation checkpoint.

Known legacy figures include:

```text
YTD Net Income:
₦94,038,821.73

June Net Income:
₦43,196,458.72

Opening Retained Earnings:
₦983,477,366.12

Closing Retained Earnings:
₦1,077,516,187.85
```

These figures are useful as **migration/report validation targets**, not hard-coded application values.

---

# 60. Foundation Acceptance Gate

Foundation is accepted only when the engineering team can demonstrate:

### Database

* migrations execute cleanly;
* organization hierarchy works;
* periods work;
* COA works;
* journals work;
* audit works.

### Accounting

* journals balance;
* posting is atomic;
* periods are enforced;
* inactive accounts are blocked;
* reversals work;
* idempotency works.

### API

* authentication works;
* authorization works;
* organization isolation works;
* API errors are standardized.

### Frontend

* login/context works;
* company context works;
* COA works;
* journal screen works;
* GL works;
* Trial Balance works;
* audit works.

### Testing

All Golden Financial Tests pass.

---

# 61. What Comes Immediately After Foundation

Do **not** jump directly into every ERP screen.

Build the first complete business vertical slice:

```text
CUSTOMER
   ↓
SALES INVOICE
   ↓
APPROVAL
   ↓
POSTING
   ↓
AR
   ↓
REVENUE
   ↓
GL
   ↓
INCOME STATEMENT
   ↓
AUDIT
```

Then the second:

```text
SUPPLIER
   ↓
PURCHASE
   ↓
GOODS RECEIPT
   ↓
SUPPLIER INVOICE
   ↓
AP
   ↓
INVENTORY / EXPENSE
   ↓
GL
```

Then:

```text
INVENTORY
   ↓
SALE
   ↓
COGS
   ↓
INVENTORY REDUCTION
   ↓
GL
```

Then:

```text
EMPLOYEE
   ↓
PAYROLL
   ↓
PAYROLL JOURNAL
   ↓
GL
```

This gives us four proven financial pathways before the platform becomes large.

---

# 62. Engineering Agent Prompt

The development engine can use the following as its Foundation instruction:

> **Implement Synbot Financial Foundation according to the Foundation Implementation Pack V1.**
>
> Build the PostgreSQL/Alembic schema first.
> Implement SQLAlchemy models and repositories.
> Implement organization scope and financial periods.
> Implement Chart of Accounts.
> Implement Accounting Events, Journal Entries and Journal Lines.
> Implement PostingService as the only authoritative financial posting mechanism.
> Implement General Ledger and Trial Balance queries.
> Implement append-only Audit Events.
> Implement FastAPI endpoints with authentication, authorization, organization isolation, idempotency and standardized errors.
> Implement the React application shell and Finance workspace.
> Implement COA, Journals, GL, Trial Balance and Audit screens.
> Implement all Golden Financial Tests.
>
> Do not implement Sales, Procurement, Inventory, Banking, Fixed Assets or Payroll yet.
>
> Do not invent tax rules.
>
> Do not invent client accounting policy.
>
> Do not create Sage compatibility functionality.
>
> Do not allow frontend code to perform authoritative accounting calculations.
>
> Do not allow AI functionality to mutate financial records.
>
> The implementation is complete only when the Foundation Acceptance Gate passes.

---

# 63. Engineering Principle

The Foundation should be considered the **financial kernel** of Synbot.

Everything else plugs into it.

```text
                 SYNBOT
                    │
        ┌───────────┴───────────┐
        │                       │
   Operational             Intelligence
    Modules                    Layer
        │                       │
        └───────────┬───────────┘
                    ↓
             ACCOUNTING CORE
                    ↓
              GENERAL LEDGER
                    ↓
             FINANCIAL TRUTH
```

Once this kernel is correct, the rest of Synbot becomes a controlled expansion rather than a collection of disconnected applications.
