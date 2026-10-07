# Synbot Financial Capability Matrix — V2

This is the deeper research version. I’m treating **V1 as the capability inventory** and **V2 as the functional specification layer**.

The central rule remains:

> **Sage is the benchmark. Synbot is the destination.**

We are not designing an import/export bridge, and we are not constrained by Sage's old architecture.

The current Sage research confirms that modern Sage has moved beyond basic bookkeeping into automated reconciliation, advanced budgeting, multi-company accounting, serialized inventory, audit trails, workflow management, role-based permissions, payroll/HR connectivity and AI assistance. ([Sage][1])

---

# 1. How to read CM V2

Each capability is evaluated against six questions:

1. **What does the business need?**
2. **What does the existing Sage system demonstrate?**
3. **What does modern accounting software add?**
4. **What should Synbot actually do?**
5. **What accounting event does it create?**
6. **What controls/reporting should surround it?**

This is important because we don't want to build a collection of screens.

We want to build a **financial transaction ecosystem**.

---

# 2. Financial Core Architecture

## Capability

### Double-entry accounting engine

**Purpose**

Every financial event must ultimately become a controlled accounting event.

### Synbot requirement

Every posted transaction must contain:

* transaction ID
* transaction type
* date
* financial period
* source module
* source document
* debit account
* credit account
* amount
* currency
* entity
* department
* cost centre where applicable
* user
* approval state
* posting state
* audit reference.

### Core rule

```text
TOTAL DEBITS = TOTAL CREDITS
```

No exception.

The client's finance team explicitly stressed that they cannot accept an imbalanced accounting result and wants the system to identify errors before they become accounting problems.

### Synbot enhancement

The user should almost never have to think:

> "Which debit account and credit account do I post?"

Instead:

> **Business event → Synbot accounting rule → journal**

That is the first major principle for the backend documentation.

---

# 3. Chart of Accounts

The client's Sage environment gives us a real-world starting point: **465 accounts** in its Chart of Accounts.

But we should not hard-code those 465 accounts.

## Synbot COA

```text
Account
 ├── Code
 ├── Name
 ├── Type
 ├── Subtype
 ├── Parent
 ├── Normal Balance
 ├── Currency
 ├── Control Account?
 ├── Manual Posting Allowed?
 ├── Tax Classification
 ├── Department
 ├── Cost Centre
 ├── Active?
 └── Effective Dates
```

### Account types

* Asset
* Liability
* Equity
* Revenue
* Cost of Goods Sold
* Expense
* Other Income
* Other Expense.

### Important requirement

Users should be able to create legitimate new accounting heads without damaging the accounting structure.

The client specifically asked for the ability to introduce new expense, income and stock heads when business needs change.

---

# 4. Accounting Rules Engine

This is one of the components I now consider **mandatory**.

Instead of putting accounting logic inside every module:

```text
Invoice code
Purchase code
Payroll code
Inventory code
Payment code
```

we create:

# Accounting Rules Engine

Example:

### Product Sale

```text
DR Accounts Receivable
CR Sales Revenue

DR Cost of Goods Sold
CR Inventory
```

### Customer Payment

```text
DR Bank/Cash
CR Accounts Receivable
```

### Supplier Invoice

```text
DR Inventory/Expense
CR Accounts Payable
```

### Supplier Payment

```text
DR Accounts Payable
CR Bank/Cash
```

### Payroll

```text
DR Salary Expense
CR Payroll Payable
```

and then:

```text
DR Payroll Payable
CR Bank
```

This is what allows the entire application to stay synchronized.

---

# 5. Transaction Lifecycle

Every financial transaction should follow a standard lifecycle.

```text
DRAFT
   ↓
VALIDATION
   ↓
APPROVAL
   ↓
POSTED
   ↓
RECONCILED
   ↓
CLOSED
```

Not every transaction needs every stage, but the engine should support the lifecycle.

### Example

Invoice:

```text
Draft
 ↓
Validate customer
 ↓
Validate stock
 ↓
Validate credit limit
 ↓
Calculate totals
 ↓
Approve
 ↓
Post
 ↓
Update AR
 ↓
Update Inventory
 ↓
Update COGS
 ↓
Update GL
```

This becomes the foundation for auditability.

---

# 6. General Ledger

The client's finance team considers the General Ledger the consolidated view of essentially all accounting activity. Their existing Sage GL contains **447,427 rows** covering January 2017–June 2026.

Therefore:

### Synbot GL must be:

**Central**

**Immutable after posting**

**Real-time**

**Traceable**

**Drillable**

### User experience

A finance user should be able to click:

```text
Expense
 ↓
Office Expenses
 ↓
₦400,000
 ↓
Transaction
 ↓
Payment
 ↓
Journal
 ↓
Source document
```

That is **financial lineage**.

---

# 7. Period Management

We need proper accounting periods.

### Functions

* Create fiscal year
* Create periods
* Open period
* Close period
* Lock period
* Reopen with authorised permission
* Year-end close
* Opening balances
* Carry-forward balances.

### Critical control

Once a period is closed:

> Normal users cannot post into it.

If correction is necessary:

> controlled adjustment/reversal process.

---

# 8. Accounts Receivable — V2

The client's existing Sage exports give us a very strong AR reference:

* 3,476 aged receivable records
* 263,332 sales journal records
* 75,039 cash receipt records
* 63,642 customer ledger records
* 112,074 customer transaction-history records
* 33,320 invoice-register records
* 1,521 customer records.

### Synbot AR lifecycle

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
Customer Ledger
 ↓
Ageing
```

Not every client workflow must use every stage.

---

## Customer Master

Should contain:

* customer code
* name
* contacts
* addresses
* payment terms
* credit limit
* price level
* discount rules
* tax classification
* account status
* outstanding balance
* ageing
* sales history
* risk indicators.

---

# 9. Credit Control Engine

This is a direct client requirement.

Example:

Customer credit limit:

**₦400,000**

Current exposure:

**₦370,000**

New invoice:

**₦80,000**

Synbot calculates:

**Projected exposure = ₦450,000**

Then:

> ⚠️ Customer credit limit will be exceeded by ₦50,000.

Options:

**Cancel**

**Request approval**

**Override with authorised permission**

The client specifically described this type of warning.

This should not merely be a UI warning.

It should be a **backend control**.

---

# 10. Aged Receivables

Default buckets should be configurable.

For example:

```text
Current
0–30
31–60
61–90
91–120
120+
```

But the system should allow the finance administrator to configure ageing rules.

### Dashboard

```text
Total AR
Current
1–30
31–60
61–90
90+
```

Then:

**Click 90+**

→ Customers

→ Invoice

→ Transaction

→ Payment history.

---

# 11. Accounts Payable — V2

AP follows:

```text
Supplier
 ↓
Purchase Request
 ↓
Purchase Order
 ↓
Goods Received
 ↓
Supplier Invoice
 ↓
AP
 ↓
Approval
 ↓
Payment
 ↓
Allocation
 ↓
Supplier Ledger
```

Modern Sage supports purchase orders, approval workflows, expense management and automated bank reconciliation; higher tiers add workflow and role-based permissions. ([Sage][2])

### Synbot enhancement

Introduce:

# Three-Way Match

```text
Purchase Order
       +
Goods Received
       +
Supplier Invoice
       ↓
   MATCH ENGINE
```

If quantities or values differ:

> ⚠️ Exception requiring review.

This is something I would classify as **ADVANCED but highly valuable**.

---

# 12. Duplicate Invoice Detection

Modern Sage now uses invoice capture and duplicate detection to reduce manual errors. ([Sage][3])

Synbot should implement this natively.

Check:

* supplier
* invoice number
* invoice date
* amount
* purchase order
* document hash
* line similarity.

Potential duplicate:

> ⚠️ Possible duplicate supplier invoice.

Then:

**Review → Confirm duplicate → Reject**

or

**Confirm legitimate duplicate → Continue**

---

# 13. Inventory — V2

Inventory is one of the most important areas because this client isn't simply selling generic goods.

They care about:

* batch
* quantity
* movement
* recall
* loan
* expiry
* returns
* reconciliation.

The client's Sage inventory dataset already contains valuation, stock status, unit activity, item costing, COGS, item master, price and buyer reports.

---

# 14. Inventory Event Engine

Rather than simply storing:

> `stock_quantity = 100`

we need to record:

```text
OPENING
PURCHASE
SALE
RETURN_IN
RETURN_OUT
TRANSFER
LOAN_OUT
LOAN_RETURN
ADJUSTMENT
DAMAGE
EXPIRY
RECALL
STOCK_COUNT
BATCH_REPLACEMENT
```

Then:

```text
Opening
+ Inbound
- Outbound
± Adjustments
= Closing
```

This gives us a genuine **inventory ledger**.

---

# 15. Inventory Accounting

Every relevant inventory event must have an accounting consequence.

The client specifically said that inventory movements must flow into the accounts so that the accounts remain balanced.

Therefore:

```text
Inventory Event
       ↓
Inventory Ledger
       +
Accounting Rule
       ↓
Journal
       ↓
GL
```

This connection must be enforced by the backend.

---

# 16. Batch Management

Each batch should support:

* batch number
* product
* manufacture date
* expiry date
* quantity
* unit cost
* supplier
* receiving transaction
* warehouse/location
* current quantity
* status.

Statuses:

```text
ACTIVE
QUARANTINED
RECALLED
EXPIRED
DAMAGED
CLOSED
```

---

# 17. Recall Engine

This becomes a specialised Synbot capability.

```text
SELECT BATCH
     ↓
TRACE OUTBOUND MOVEMENTS
     ↓
IDENTIFY CUSTOMERS
     ↓
IDENTIFY INVOICES
     ↓
IDENTIFY QUANTITIES
     ↓
CREATE RECALL
     ↓
CONTACT CUSTOMERS
     ↓
TRACK RETURNS
     ↓
REPLACEMENT/DISPOSITION
     ↓
CLOSE RECALL
```

The requirement to search by batch and identify customers and quantities comes directly from the meeting.

This is a capability I would put in the **Synbot differentiator** category.

---

# 18. Stock Loan Engine

This should be an explicit transaction type.

```text
LOAN OUT
```

must **not** behave like:

```text
SALE
```

The client specifically distinguishes loan stock from sales and requires batch tracking when returned stock comes back under another batch.

### Required records

```text
Loan ID
Customer
Product
Original Batch
Quantity Loaned
Date Out
Expected Return
Returned Quantity
Returned Batch
Outstanding Quantity
Status
```

Possible status:

```text
OPEN
PARTIALLY_RETURNED
RETURNED
OVERDUE
CONVERTED_TO_SALE
WRITTEN_OFF
```

The last two are **research items** rather than assumptions.

---

# 19. Stock Returns

### Return Inward

Customer → Company

Effects:

* inventory increases
* customer balance adjusted
* original sale referenced
* batch recorded
* reason captured
* accounting adjustment generated.

### Return Outward

Company → Supplier

Effects:

* inventory decreases
* supplier balance adjusted
* original purchase referenced
* batch recorded
* accounting adjustment generated.

---

# 20. Cash & Banking — V2

The existing Sage reconciliation dataset is complete across:

* account reconciliation
* account register
* bank deposits
* deposits in transit
* outstanding checks
* other outstanding items. 

Synbot should therefore have a proper:

# Banking Subsystem

```text
Bank Accounts
      ↓
Bank Transactions
      ↓
Matching Engine
      ↓
Reconciliation
      ↓
Exceptions
      ↓
Accounting
```

Modern Sage also provides automated reconciliation and live bank connectivity. ([Sage][2])

---

# 21. Bank Matching Engine

Potential matching signals:

* amount
* date
* reference
* account
* customer
* supplier
* invoice number
* transaction description.

Result:

```text
MATCHED
LIKELY MATCH
UNMATCHED
DUPLICATE
EXCEPTION
```

AI can assist with matching, but final accounting posting should remain controlled.

---

# 22. Cash Flow Engine

Cash flow shouldn't be a manually prepared report.

Every cash/bank event should automatically contribute to:

```text
Operating Activities
Investing Activities
Financing Activities
```

The client specifically expects cash movements to flow automatically into the Cash Flow Statement.

---

# 23. Fixed Assets — V2

The client's discussion explicitly identified:

* furniture/fittings
* plant/machinery
* office equipment
* land/buildings
* investments
* depreciation.

### Asset lifecycle

```text
Acquire
 ↓
Capitalise
 ↓
Depreciate
 ↓
Transfer/Revalue
 ↓
Dispose
 ↓
Gain/Loss
```

The asset register should connect directly to GL and reporting.

---

# 24. Payroll + HR — V2

This is now officially a **CORE subsystem**.

Modern Sage supports payroll alongside accounting and offers HR/payroll integration. ([Sage][2])

But Synbot's design should be deeper.

## Employee master

```text
Employee
 ├── Personal Information
 ├── Employment
 ├── Department
 ├── Position
 ├── Salary
 ├── Allowances
 ├── Deductions
 ├── Attendance
 ├── Leave
 ├── Loans
 ├── Advances
 ├── Payroll History
 └── Documents
```

---

# 25. Payroll Engine

```text
Employee
 ↓
Attendance/Leave/Overtime
 ↓
Gross Pay
 ↓
Allowances
 ↓
Deductions
 ↓
Statutory Calculations
 ↓
Net Pay
 ↓
Approval
 ↓
Payslip
 ↓
Payment
 ↓
Payroll Journal
 ↓
GL
```

### Important research item

Because this is a Nigerian implementation, we should **not yet hard-code tax, pension or statutory payroll rules from generic Sage documentation**.

That needs a dedicated **Nigeria Payroll & Statutory Compliance Research** stage.

We need to establish the current applicable rules before backend specification.

---

# 26. HR ↔ Payroll ↔ Finance

This is the relationship I recommend:

```text
                STAFF
                  │
          ┌───────┴───────┐
          │               │
         HR            ATTENDANCE
          │               │
          └───────┬───────┘
                  │
               PAYROLL
                  │
             PAYROLL GL
                  │
              FINANCE
```

So changing an employee's:

* department
* salary
* employment status
* allowance
* deduction

can feed the correct downstream systems subject to approval.

---

# 27. Expense Management

Expense workflow:

```text
Expense Request
 ↓
Approval
 ↓
Expense Classification
 ↓
Payment
 ↓
Journal
 ↓
GL
```

Possible dimensions:

* employee
* department
* cost centre
* project
* account
* supplier
* expense category.

---

# 28. Budgeting

Modern Sage explicitly supports advanced budgeting and reporting by department. ([Sage][1])

Synbot should support:

```text
Annual Budget
      ↓
Monthly Allocation
      ↓
Department
      ↓
Cost Centre
      ↓
Account
```

Then:

```text
Actual
vs
Budget
=
Variance
```

And:

```text
Actual + Forecast
=
Expected Year End
```

---

# 29. Management Accounting

This is an opportunity to go beyond Sage.

We should eventually support:

* department profitability
* product profitability
* customer profitability
* branch profitability
* cost-centre performance
* contribution margin
* gross margin
* operating margin
* budget variance
* trend analysis.

This is where the **financial analyst** layer of Synbot becomes valuable.

---

# 30. Internal Accounting Review

This deserves to be a formal subsystem.

The client's existing Sage workflow has an internal accounting review mechanism that highlights discrepancies such as AR not agreeing with ageing reports.

Synbot should turn this into:

# Financial Integrity Monitor

Continuously test:

### Accounting integrity

* Debits = Credits
* No orphan journal lines
* Valid accounts
* Valid periods
* Valid references.

### AR integrity

```text
AR Control Account
=
Sum of Customer Balances
```

### AP integrity

```text
AP Control Account
=
Sum of Supplier Balances
```

### Inventory integrity

```text
Inventory GL
=
Valuation Engine
```

### Bank integrity

```text
Bank Ledger
vs
Reconciliation
```

### Payroll integrity

```text
Payroll Liability
=
Unpaid Payroll
```

This becomes one of Synbot's most important control mechanisms.

---

# 31. Audit Engine

Every material financial event should create an audit event.

```text
WHO
WHAT
WHEN
WHERE
WHY
SOURCE
BEFORE
AFTER
APPROVAL
```

### Accounting correction

Never:

```text
DELETE
```

Instead:

```text
ORIGINAL
   ↓
REVERSAL
   ↓
CORRECTED TRANSACTION
```

This gives us an auditable history.

The client's existing report inventory identifies Sage's audit trail as a gap, while modern Sage includes audit trails in higher tiers.  ([Sage][1])

---

# 32. Workflow & Approvals

Modern Sage's higher tiers include role-based permissions and workflow management. ([Sage][2])

Synbot should make workflow a **platform capability**, not something specific to finance.

Example:

```text
Transaction
 ↓
Approval Rule
 ↓
Approver
 ↓
Decision
 ↓
Post
```

Examples:

### Purchase

₦0–₦100k → Officer

₦100k–₦1m → Manager

₦1m+ → Finance Director

Those thresholds are examples only; actual client rules must be researched.

---

# 33. Security Model

We should have:

### Role

What the user generally does.

### Permission

What action they can perform.

### Scope

Which data they can access.

For example:

```text
Payroll Officer
    ↓
Can create payroll
Can view employees
Cannot approve payroll
Cannot change GL
```

while:

```text
Finance Director
    ↓
Can approve payroll
Can approve journals
Can close periods
Can view all financial data
```

---

# 34. Reporting Engine — V2

The client's Sage corpus already gives us a substantial report oracle.

### Financial Statements

* Balance Sheet
* Income Statement
* Cash Flow
* Retained Earnings
* Financial Position
* GL Account Summary.

### GL

* General Ledger
* Trial Balance
* General Journal
* Chart of Accounts
* Cash Account Register
* Account Variance.

### AR

* Aged Receivables
* Sales Journal
* Cash Receipts
* Customer Ledger
* Transaction History
* Sales History
* Invoice Register
* Customer Master
* Contacts.

### AP

* Aged Payables
* Purchase Journal
* Vendor Ledger
* Vendor History
* Open AP
* Items Purchased
* Vendor Master.

### Inventory

* Valuation
* Stock Status
* Unit Activity
* Costing
* COGS
* Item Master
* Price
* Buyer Report.

### Banking

* Reconciliation
* Account Register
* Deposits
* Deposits in Transit
* Outstanding Items.

These actual report categories give us the first **report acceptance-test catalogue**. 

---

# 35. Drill-Down Reporting

Every report should eventually follow:

```text
REPORT
 ↓
SUMMARY
 ↓
TRANSACTION
 ↓
JOURNAL
 ↓
SOURCE EVENT
```

Example:

**Balance Sheet → Inventory**

→ Inventory account

→ ₦450m

→ Inventory valuation

→ Product

→ Batch

→ Stock movement

→ Purchase/Sale/Adjustment.

This is the difference between:

> "Here's the number."

and:

> **"Here's the number, and here's exactly where it came from."**

---

# 36. AI Finance Layer

Current Sage already has AI features including Sage Copilot, AI report finding, AI document capture and AI-assisted financial insights. ([Sage][3])

Synbot should build the AI layer **above the financial truth**, not inside the accounting engine.

### Finance Agent

```text
User Question
      ↓
Intent Detection
      ↓
Financial Query Engine
      ↓
Authoritative Data
      ↓
Calculation
      ↓
Explanation
```

Example:

> "Why did profit fall in August?"

Agent should retrieve:

* August revenue
* July revenue
* COGS
* expenses
* major variances

and produce a grounded explanation.

---

# 37. Financial Anomaly Engine

Eventually:

```text
Transaction
     ↓
Rules
     +
Historical Pattern
     +
User Behaviour
     +
Financial Context
     ↓
Risk Score
```

Possible flags:

* duplicate payment
* unusual amount
* unusual account
* unusual timing
* repeated invoice
* abnormal discount
* unexpected stock adjustment
* unusual journal entry
* suspicious payroll change.

This should be **decision support**, not autonomous financial posting.

---

# 38. Multi-Company

This now becomes particularly important because of the wider Synbot architecture.

Modern Sage supports multiple companies and consolidated reporting in higher tiers. ([Sage][1])

Synbot should support:

```text
Organization
 ├── Company A
 │    ├── Branch
 │    ├── Department
 │    └── Cost Centres
 │
 ├── Company B
 │    ├── Branch
 │    └── Department
 │
 └── Company C
```

Then:

### Company view

Individual books.

### Group view

Consolidated management view.

Intercompany accounting should be a **research item**, but the architecture should leave room for it.

---

# 39. Currency

We need to support:

* base currency
* transaction currency
* exchange rate
* exchange-rate date
* realised FX gain/loss
* unrealised FX gain/loss.

Modern Sage supports foreign-currency transactions in its UK product. ([Sage][4])

For Synbot, the exact Nigerian/client currency requirements need confirmation before we lock the accounting model.

---

# 40. What Synbot Should NOT Copy From Sage

This is becoming equally important.

We should **not** reproduce:

* old Sage navigation
* old report-oriented architecture
* legacy terminology where unnecessary
* manual journal-heavy workflows
* fragmented modules
* disconnected inventory/accounting
* spreadsheet-style reconciliation
* unnecessary US-specific functionality.

Instead:

> **Use Sage's accounting behaviour as the benchmark, not Sage's interface or internal architecture.**

---

# 41. CM V2 Priority Classification

### Tier 0 — Accounting Integrity

These cannot be compromised.

| Capability          |
| ------------------- |
| Double-entry        |
| GL                  |
| COA                 |
| Journals            |
| Periods             |
| Trial Balance       |
| Accounting rules    |
| Audit               |
| Validation          |
| Financial integrity |

---

### Tier 1 — Core Business Finance

| Capability           |
| -------------------- |
| AR                   |
| AP                   |
| Sales                |
| Purchases            |
| Cash                 |
| Banking              |
| Reconciliation       |
| Inventory            |
| Fixed Assets         |
| Financial Statements |
| Budgeting            |

---

### Tier 2 — Workforce Finance

| Capability         |
| ------------------ |
| HR                 |
| Employee Master    |
| Attendance         |
| Leave              |
| Payroll            |
| Staff Loans        |
| Staff Advances     |
| Payroll Accounting |

---

### Tier 3 — Client-Specific Operations

| Capability                 |
| -------------------------- |
| Batch                      |
| Recall                     |
| Loan Stock                 |
| Batch Replacement          |
| Stock Returns              |
| Stock Adjustment           |
| Expiry                     |
| Credit Control             |
| Internal Accounting Review |

---

### Tier 4 — Intelligence

| Capability                 |
| -------------------------- |
| Finance AI                 |
| Anomaly Detection          |
| Forecasting                |
| Profitability Intelligence |
| Cash Forecast              |
| Collection Intelligence    |
| Supplier Intelligence      |
| Inventory Intelligence     |

---

# 42. Research Gaps We Should NOT Guess

This is important.

Before we freeze the backend architecture, these need dedicated research:

### Nigerian payroll

* PAYE
* pension
* statutory deductions
* payroll reporting
* current regulatory requirements.

### Nigerian taxation

* VAT treatment
* withholding tax
* applicable tax classifications
* exemptions
* tax reporting.

### Inventory valuation

We need to establish exactly which costing method the client wants.

Modern Sage supports multiple inventory costing approaches depending on product/version. ([Sage][2])

We shouldn't simply choose one.

### Multi-company

Need to define:

* separate books
* consolidated reporting
* intercompany transactions
* shared customers/vendors
* shared inventory
* entity-level COA.

### Payroll/HR

Need client-specific:

* salary structures
* allowances
* deductions
* leave
* overtime
* loans
* approval hierarchy.

### Purchase workflow

Need to establish whether the client actually operates:

```text
Request → PO → GRN → Invoice
```

or uses a simpler process.

The existing Sage exports do **not** establish that conclusively. 

### Job/project costing

The client's Sage job file was empty, so we shouldn't assume it is required merely because Sage supports it. 

---

# 43. The New Synbot Financial Model

After CM V2, I think our conceptual model is now much clearer:

```text
                    SYNBOT
                       │
        ┌──────────────┼──────────────┐
        │              │              │
     OPERATIONS       PEOPLE        FINANCE
        │              │              │
 Sales/Purchases      HR          Accounting
 Inventory          Staff        AR/AP
 Banking            Payroll      Banking
 Logistics          Attendance   Assets
                    Leave        Budget
                       │              │
                       └──────┬───────┘
                              │
                    ACCOUNTING ENGINE
                              │
                     CONTROL ENGINE
                              │
                      REPORTING ENGINE
                              │
                   FINANCIAL INTELLIGENCE
                              │
                       FINANCE AI
```

And the most important connection is:

```text
OPERATIONS
    ↓
BUSINESS EVENT
    ↓
TRANSACTION ENGINE
    ↓
ACCOUNTING RULE
    ↓
JOURNAL
    ↓
GENERAL LEDGER
    ↓
FINANCIAL STATEMENTS
    ↓
ANALYTICS / AI
```

That is the architecture I would want our eventual backend agents to understand **before they write a single financial table**.

---

# 44. CM V2 Verdict

The research has now changed the scope substantially.

We are no longer building:

> **"A Sage replacement."**

We are building:

# **Synbot Financial Operating System**

with five interconnected layers:

```text
1. BUSINESS OPERATIONS
       ↓
2. TRANSACTION ENGINE
       ↓
3. ACCOUNTING ENGINE
       ↓
4. CONTROL + REPORTING ENGINE
       ↓
5. FINANCIAL INTELLIGENCE
```

And HR/Payroll sits directly inside the business-to-finance chain:

```text
HR → Payroll → Accounting → GL → Financial Statements
```

The client's actual Sage data gives us a valuable **historical reference corpus**, including hundreds of thousands of real transactions and the corresponding financial reports. That means we can eventually do something powerful: **build Synbot against the real books and use the historical Sage outputs as reconciliation/acceptance tests**, rather than relying purely on theoretical test data. 

### The next artifact should therefore be the **Synbot Financial Workflow Map**.

That is where we take every major capability from CM V2 and map:

**User action → business event → validation → accounting rule → journal → affected modules → database state → report impact → audit event → approval → UI response.**

Once that is complete, we will have enough understanding to start designing the **actual backend architecture and frontend architecture**, rather than prematurely jumping into tables and screens.

[1]: https://www.sage.com/en-us/products/sage-50/features/?utm_source=chatgpt.com "Popular Sage 50 Features | Sage US"
[2]: https://www.sage.com/en-us/products/sage-50/pricing/?utm_source=chatgpt.com "Sage 50 Pricing Plans | Sage US"
[3]: https://www.sage.com/en-gb/products/sage-50-accounts/?trk=article-ssr-frontend-pulse_little-text-block&utm_source=chatgpt.com "Sage 50 Accounts - Finance Software | Sage UK"
[4]: https://www.sage.com/en-gb/products/sage-50-accounts/features/invoice-payments/?utm_source=chatgpt.com "Sage 50 Accounts Invoice Payments | Sage UK"
