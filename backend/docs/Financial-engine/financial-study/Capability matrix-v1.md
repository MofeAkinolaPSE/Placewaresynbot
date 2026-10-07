Yes. We now have enough evidence to establish **Version 1 of the Synbot Financial Capability Matrix**.

The important thing is that this is **not a “Sage clone checklist.”** We are using three layers of evidence:

* **Client reality:** what the finance team actually needs and how they currently work.
* **Sage 50 2013:** the existing accounting/reporting baseline, including the actual exported data.
* **Modern Sage:** capabilities that have evolved since 2013—automation, controls, advanced inventory, payroll/HR, workflows, AI, etc. ([Sage][1])

And our target is the fourth layer:

> **Synbot Financial Ecosystem — a native accounting, payroll, HR and financial intelligence platform that can operate independently of Sage.**

---

# Synbot Financial Capability Matrix — V1

### Capability status legend

| Status           | Meaning                                                           |
| ---------------- | ----------------------------------------------------------------- |
| **CORE**         | Fundamental to Synbot Finance                                     |
| **REQUIRED**     | Needed for this client's operation                                |
| **ADVANCED**     | Capability we should build beyond the client's current Sage usage |
| **INTELLIGENCE** | Automation/AI layer                                               |
| **FUTURE**       | Useful but not required for the first financial release           |
| **RESEARCH**     | Needs further investigation before architecture is finalized      |

---

## 1. Accounting Foundation

This is the heart of the entire system.

| Capability                | Sage 2013 | Modern Sage | Synbot Target                                          | Priority |
| ------------------------- | --------- | ----------- | ------------------------------------------------------ | -------- |
| Chart of Accounts         | ✓         | ✓           | **Native dynamic COA**                                 | CORE     |
| Account hierarchy         | ✓         | ✓           | Parent/child account structure                         | CORE     |
| Account types             | ✓         | ✓           | Asset, Liability, Equity, Revenue, COGS, Expense, etc. | CORE     |
| General Ledger            | ✓         | ✓           | **Central accounting ledger**                          | CORE     |
| General Journal           | ✓         | ✓           | Controlled manual journals                             | CORE     |
| Trial Balance             | ✓         | ✓           | Real-time                                              | CORE     |
| Double-entry accounting   | ✓         | ✓           | **Mandatory system rule**                              | CORE     |
| Automatic journal posting | ✓         | ✓           | **Every financial event generates accounting entries** | CORE     |
| Financial periods         | ✓         | ✓           | Open/closed/locked periods                             | CORE     |
| Year-end closing          | ✓         | ✓           | Controlled automated closing                           | REQUIRED |
| Opening balances          | ✓         | ✓           | Controlled migration/opening balance engine            | REQUIRED |
| Account variance          | ✓         | ✓           | Real-time variance analysis                            | ADVANCED |
| Budgeting                 | Partial   | ✓           | Full budget engine                                     | REQUIRED |
| Multiple budgets          | ✓         | ✓           | Budget versions/scenarios                              | ADVANCED |

The client's existing Sage data contains a **465-account Chart of Accounts**, a General Ledger with **447,427 rows**, General Journal with **22,298 rows**, and a Trial Balance, giving us an unusually strong real-world accounting reference dataset.

### Design conclusion

The **General Ledger should not be a report module**.

It should be the accounting system's central source of truth.

For example:

**Invoice**

→ Sales transaction
→ AR entry
→ Revenue entry
→ Inventory reduction
→ COGS entry
→ Customer ledger
→ Inventory ledger
→ General Ledger
→ Trial Balance
→ P&L
→ Balance Sheet
→ Cash-flow impact when payment occurs.

That is the architecture we should ultimately document.

---

# 2. Financial Statements

The client already relies heavily on these.

| Capability                                 | Current Evidence | Synbot          |
| ------------------------------------------ | ---------------- | --------------- |
| Balance Sheet                              | Sage ✓           | **CORE**        |
| Income Statement                           | Sage ✓           | **CORE**        |
| Monthly P&L                                | Sage ✓           | CORE            |
| YTD P&L                                    | Sage ✓           | CORE            |
| Comparative P&L                            | Sage ✓           | REQUIRED        |
| 12-period analysis                         | Sage ✓           | ADVANCED        |
| Revenue vs Budget                          | Sage ✓           | REQUIRED        |
| Expense vs Budget                          | Sage ✓           | REQUIRED        |
| Cash Flow Statement                        | Sage ✓           | **CORE**        |
| Retained Earnings                          | Sage ✓           | CORE            |
| Statement of Financial Position            | Sage ✓           | CORE            |
| GL Account Summary                         | Sage ✓           | CORE            |
| Working Trial Balance                      | Not held         | RESEARCH        |
| Statement of Changes in Financial Position | Not held         | RESEARCH        |
| EPS/Earnings Statement                     | Not held         | FUTURE/RESEARCH |

The client's actual Sage exports already contain Balance Sheet, Income Statement, Cash Flow, Retained Earnings, Statement of Financial Position and GL Account Summary, with statements tying to **30 June 2026**.

### Important architectural principle

We should **not build these statements as independent calculations**.

They should all be generated from the same accounting engine.

That gives us:

> **One transaction → one accounting truth → many reports.**

This is much safer than having separate logic for the Balance Sheet, GL, inventory report, AR report, etc.

---

# 3. Accounts Receivable

This is one of the client's major operational areas.

| Capability                   |                     Sage 2013 | Synbot Target |
| ---------------------------- | ----------------------------: | ------------- |
| Customer master              |                             ✓ | CORE          |
| Customer contacts            |                             ✓ | CORE          |
| Customer ledger              |                             ✓ | CORE          |
| Customer transaction history |                             ✓ | CORE          |
| Sales journal                |                             ✓ | CORE          |
| Invoice register             |                             ✓ | CORE          |
| Cash receipts                |                             ✓ | CORE          |
| Aged receivables             |                             ✓ | **CORE**      |
| Customer sales history       |                             ✓ | REQUIRED      |
| Items sold by customer       |                             ✓ | REQUIRED      |
| Customer statements          |                             — | CORE          |
| Credit limits                |            Client requirement | **CORE**      |
| Credit-limit warnings        |            Client requirement | **CORE**      |
| Partial payments             | Modern accounting expectation | CORE          |
| Payment allocation           |                      Required | CORE          |
| Overpayments                 |                      Required | CORE          |
| Credit notes                 |                      Required | CORE          |
| Debit notes                  |                      Required | CORE          |
| Write-offs                   |                      Required | REQUIRED      |
| Collection tracking          |                      Advanced | ADVANCED      |
| Automated reminders          |                   Modern Sage | ADVANCED      |
| Customer profitability       |             Modern capability | ADVANCED      |
| Customer risk score          |                        Synbot | INTELLIGENCE  |

The client explicitly wants **credit-limit control**, including a warning before a customer's outstanding balance exceeds their configured limit.

Modern Sage also supports real-time customer balances, invoice tracking and automated payment reminders. ([Sage][2])

---

# 4. Accounts Payable

| Capability                   |                        Sage 2013 | Synbot Target             |
| ---------------------------- | -------------------------------: | ------------------------- |
| Supplier master              |                                ✓ | CORE                      |
| Supplier ledger              |                                ✓ | CORE                      |
| Purchase journal             |                                ✓ | CORE                      |
| Supplier transaction history |                                ✓ | CORE                      |
| Open AP invoices             |                                ✓ | CORE                      |
| Aged payables                |                                ✓ | **CORE**                  |
| Items purchased              |                                ✓ | REQUIRED                  |
| Cash disbursement journal    |             Missing from exports | **CORE**                  |
| Payment allocation           |                         Required | CORE                      |
| Supplier statement           |                         Required | CORE                      |
| Payment scheduling           |                           Modern | ADVANCED                  |
| Duplicate invoice detection  |                           Modern | **ADVANCED/INTELLIGENCE** |
| Supplier credit limits/terms |                         Required | REQUIRED                  |
| Purchase orders              |      Not currently proven in use | REQUIRED/RESEARCH         |
| Goods received               | Required for robust inventory/AP | REQUIRED                  |
| Three-way matching           |            Modern ERP capability | ADVANCED                  |

The current client exports contain AP invoices and supplier history, but the **Cash Disbursements Journal is missing**, which means this is one of the areas where our research corpus does not yet give us the complete picture.

This becomes a research item rather than something we should simply assume.

---

# 5. Inventory & Stock Accounting

This is where the client's requirements become considerably more sophisticated than a basic accounting package.

### Core inventory

| Capability             | Synbot   |
| ---------------------- | -------- |
| Item master            | CORE     |
| Product categories     | CORE     |
| Units of measure       | CORE     |
| Batch management       | **CORE** |
| Expiry tracking        | CORE     |
| Opening stock          | CORE     |
| Purchases              | CORE     |
| Sales                  | CORE     |
| Closing stock          | CORE     |
| Stock valuation        | CORE     |
| Cost of goods sold     | CORE     |
| Stock adjustments      | CORE     |
| Stock transfers        | REQUIRED |
| Stock reconciliation   | CORE     |
| Physical stock count   | REQUIRED |
| Reorder levels         | ADVANCED |
| Stock profitability    | ADVANCED |
| Stock movement history | CORE     |

The current Sage inventory corpus includes valuation, stock status, unit activity, costing, COGS, item master, pricing and buyer reports. The Inventory Unit Activity report specifically captures opening, purchased, sold/adjusted and closing quantities.

---

## 6. Client-specific inventory workflows

This is where Synbot needs to go beyond simply copying Sage.

### Return Inward

Customer returns goods.

**Sale**

→ Customer receives goods
→ Customer returns goods
→ Return Inward
→ Inventory increases
→ Relevant accounting entries reverse/adjust
→ Customer balance adjusts.

The client specifically requested this workflow.

### Return Outward

Supplier return.

**Purchase**

→ Goods received
→ Goods returned to supplier
→ Inventory decreases
→ Supplier balance adjusts
→ Accounting entries generated.

### Stock Adjustment

Should support:

* damage
* expiry
* shortage
* excess
* stock count correction
* write-off
* batch correction
* other approved adjustment reasons.

The client was explicit that **every inventory movement must reflect in the accounts**.

That becomes one of our most important architectural requirements.

---

# 7. Batch Recall Engine

This deserves its own capability.

The client wants to be able to say:

> “Find everyone who received Batch X.”

Synbot should return:

**Batch X**

→ Product
→ Quantity originally received
→ Quantity sold
→ Customers
→ Invoice numbers
→ Dates
→ Quantities per customer
→ Customer contact details
→ Current stock remaining.

Then:

**Recall Campaign**

→ Select batch
→ Identify affected customers
→ Create recall case
→ Track notification
→ Track returned quantity
→ Track replacement
→ Close recall.

The meeting explicitly describes searching by batch number to determine **which customers bought that particular batch and how much they bought**.

This is an area where Synbot can become substantially more operational than traditional accounting software.

---

# 8. Loan Stock

This is another **client-specific requirement that should become a first-class transaction type**.

The client's workflow is:

**Stock**

100 units

↓

**Loan Out**

5 units

↓

Available stock = 95

But:

**Loan ≠ Sale**

Therefore:

* no sales revenue
* no normal sales invoice
* no COGS sale transaction
* inventory movement still recorded
* loan quantity tracked
* batch tracked.

When the goods come back:

**Loan Return**

The returned goods may have a **different batch number**.

Synbot must therefore preserve:

* original batch
* returned batch
* quantity loaned
* quantity returned
* outstanding quantity
* replacement batch
* current batch location.

This is a strong example of why we're not simply copying Sage screens. The **business event model** needs to be richer.

---

# 9. Cash & Banking

| Capability                | Synbot       |
| ------------------------- | ------------ |
| Cash accounts             | CORE         |
| Bank accounts             | CORE         |
| Petty cash                | CORE         |
| Cash receipts             | CORE         |
| Cash payments             | CORE         |
| Bank deposits             | CORE         |
| Bank transfers            | CORE         |
| Bank charges              | CORE         |
| Account register          | CORE         |
| Bank reconciliation       | **CORE**     |
| Deposits in transit       | CORE         |
| Outstanding payments      | CORE         |
| Other outstanding items   | CORE         |
| Bank feeds                | ADVANCED     |
| Auto matching             | ADVANCED     |
| Reconciliation exceptions | INTELLIGENCE |

The existing client corpus has a complete account-reconciliation area, including reconciliation, account register, deposits, deposits in transit, outstanding checks and other outstanding items.

Modern Sage adds automated bank feeds and auto-clearing/matching of transactions. ([Sage][1])

### Synbot opportunity

We shouldn't stop at:

> “Bank reconciliation completed.”

We should produce:

> **Reconciliation health: 98.7% matched**

with:

* matched
* unmatched
* duplicates
* unexplained differences
* old outstanding items
* suspicious transactions.

---

# 10. Fixed Assets

The client specifically discussed assets such as:

* furniture and fittings
* plant and machinery
* office equipment
* land and buildings
* investments.

Depreciation was also discussed, including posting depreciation through the journal.

Therefore:

| Capability               | Synbot   |
| ------------------------ | -------- |
| Fixed Asset Register     | CORE     |
| Asset categories         | CORE     |
| Acquisition              | CORE     |
| Capitalisation           | CORE     |
| Asset location           | REQUIRED |
| Asset custodian          | REQUIRED |
| Depreciation             | CORE     |
| Depreciation schedules   | CORE     |
| Accumulated depreciation | CORE     |
| Asset transfer           | REQUIRED |
| Asset disposal           | REQUIRED |
| Gain/loss on disposal    | REQUIRED |
| Revaluation              | ADVANCED |
| Asset audit history      | CORE     |

---

# 11. Payroll + HR

Your correction is important here.

**Payroll is not being dropped simply because the client's current Sage employee file is empty.**

The existing export tells us only that payroll **wasn't being used in this particular Sage installation**. It does not mean Synbot shouldn't have payroll.

Modern Sage demonstrates that payroll and HR are increasingly connected: payroll processing, employee records, payslips, leave, time tracking, departments/cost centres and employee self-service are now part of the broader ecosystem. ([Sage][3])

### Synbot Payroll

**Employee**

→ Employment details
→ Salary structure
→ Allowances
→ Deductions
→ Attendance/time
→ Leave
→ Overtime
→ Bonuses
→ Payroll run
→ Approval
→ Payslip
→ Payment
→ Payroll journal
→ GL
→ Financial statements.

### HR/Staff Dashboard

The staff record should therefore become the common entity connecting:

**HR**

* Employee profile
* Department
* Position
* Employment history
* Documents
* Leave
* Attendance
* Performance
* Disciplinary records
* Training
* Staff status

↓

**Payroll**

* Salary
* Allowances
* Deductions
* Tax
* Pension
* Loans
* Bonuses
* Payroll history
* Payslips

↓

**Finance**

* Salary expense
* Payroll liabilities
* Staff advances
* Staff loans
* Payment
* General Ledger.

This is precisely the sort of integration modern payroll systems demonstrate, including automatic salary journal posting into accounting. ([Sage][3])

---

# 12. Expense Management

The client specifically wants the ability to introduce new expense heads when necessary.

Therefore:

**Expense**

→ Expense category
→ Account mapping
→ Department
→ Cost centre
→ Employee/vendor
→ Approval
→ Payment
→ GL.

And the system must allow authorised users to create new:

* expense heads
* income heads
* stock categories/accounts

without breaking the accounting structure.

That requirement comes directly from the meeting.

---

# 13. Budgeting & Management Accounting

Modern Sage has moved considerably further here with advanced budgeting and departmental reporting. ([Sage][1])

Synbot should therefore support:

* annual budgets
* monthly budgets
* departmental budgets
* cost-centre budgets
* account budgets
* actual vs budget
* variance
* variance %
* budget revisions
* forecast
* scenario planning.

Eventually:

> **Budget → Actual → Variance → Explanation → Forecast**

rather than simply producing a static budget report.

---

# 14. Internal Accounting Control Engine

This is one of the **most important discoveries from the client meeting**.

The client doesn't merely want accounting.

They want Synbot to **prevent bad accounting**.

The meeting specifically identifies:

* duplicate check numbers
* incorrect postings
* AR discrepancies
* credit-limit violations
* incorrect classification of charges
* imbalance
* reconciliation differences.

So we need:

### Financial Control Engine

Every transaction passes through:

**Validation**

→ Account valid?
→ Period open?
→ Customer/vendor valid?
→ Duplicate reference?
→ Debit = Credit?
→ Inventory available?
→ Credit limit exceeded?
→ Tax treatment valid?
→ Required approval?
→ Correct account classification?
→ Supporting reference exists?

Only then:

**POST**

This becomes a central Synbot service.

---

# 15. Audit Trail

This should be **stronger than the client's current Sage implementation**.

The existing inventory specifically identifies Sage's Audit Trail as a missing export and notes that auditors expect it.

Synbot should record:

* who
* what
* when
* record affected
* previous value
* new value
* reason
* source
* transaction ID
* approval
* IP/session where appropriate
* reversal/correction relationship.

And importantly:

### No destructive accounting edits.

Instead of:

> Edit transaction

we should have:

> Reverse → Correct → Repost

That preserves accounting history.

Modern Sage itself now emphasizes audit trails and transaction/user history. ([Sage][4])

---

# 16. Reporting Engine

This is where we should take a major architectural decision.

Don't build:

> `balance_sheet.py`
> `profit_loss.py`
> `inventory_report.py`
> `ar_report.py`

as disconnected report logic.

Build:

### Financial Reporting Engine

with:

**Ledger → Dimensions → Aggregations → Report Definition → Presentation**

Every report should support:

* date range
* financial period
* company
* branch
* department
* cost centre
* account
* customer
* supplier
* product
* batch
* transaction type.

And preferably:

### Drill-down

**Net Profit**

→ Revenue
→ Customer
→ Invoice
→ Invoice line
→ Accounting transaction
→ Journal entry.

That creates **financial lineage**.

---

# 17. Finance Intelligence Layer

This is where Synbot begins to become more than Sage.

Current Sage already has AI functionality such as Sage Copilot and AI-driven financial assistance. ([Sage][5])

But Synbot can make the AI layer native to our architecture.

### Finance Agent

Questions such as:

> “Why did profit fall this month?”

> “Which customers owe us more than 60 days?”

> “Which invoices are overdue?”

> “What caused the increase in expenses?”

> “Which products have declining margins?”

> “Which inventory has been stagnant?”

> “Why hasn't this bank account reconciled?”

> “Which suppliers are due for payment?”

> “Show me unusual accounting entries.”

The AI **does not write directly to financial tables**.

It queries the accounting/reporting layer and explains the result.

---

# 18. Financial Control Tower

Eventually the finance dashboard becomes something like:

### FINANCE CONTROL TOWER

**Cash**
₦XXX

**Receivables**
₦XXX

**Payables**
₦XXX

**Inventory**
₦XXX

**Revenue**
₦XXX

**Gross Profit**
₦XXX

**Net Profit**
₦XXX

**Overdue AR**
₦XXX

**Outstanding AP**
₦XXX

**Bank Reconciliation**
98%

**Accounting Exceptions**
7

**Pending Approvals**
12

**Payroll Due**
3 days

---

Then underneath:

### AI Insights

> ⚠️ Receivables above 60 days increased 18% this month.

> ⚠️ Inventory value increased while sales volume declined.

> ⚠️ 3 transactions require accounting review.

> ℹ️ Payroll expense is 7.2% above the monthly budget.

That is the beginning of **Synbot Finance Intelligence**.

---

# 19. Security & Access Control

Modern Sage separates capabilities by user roles and permissions, particularly in higher tiers. ([Sage][6])

Synbot should go further because we're building the platform ourselves.

### Roles

* Super Admin
* Finance Director
* Accountant
* Finance Officer
* Accounts Receivable Officer
* Accounts Payable Officer
* Inventory Officer
* HR Manager
* Payroll Officer
* Auditor
* Manager
* Employee.

And permissions should be **action-based**, not just module-based.

For example:

> Can view payroll
> Can create payroll
> Can approve payroll
> Can release payroll payment

These are four different permissions.

---

# 20. Multi-Company / Enterprise Architecture

This becomes particularly important for the wider Synbot platform.

We should not design Finance around a single company.

The financial hierarchy should ultimately support:

**Organization**

→ Legal Entity
→ Branch
→ Department
→ Cost Centre
→ Account
→ Transaction.

This will fit the larger Synbot multi-company architecture we have already been discussing.

---

# 21. Modern Sage Capabilities We Should Absorb

The current Sage research gives us several capabilities that weren't part of the old 2013 baseline:

| Modern capability                   | Synbot     |
| ----------------------------------- | ---------- |
| Automated bank reconciliation       | ✓          |
| Bank feeds                          | ✓          |
| Advanced budgeting                  | ✓          |
| Multi-company                       | ✓          |
| Department reporting                | ✓          |
| Serialized inventory                | ✓          |
| Advanced job costing                | ✓/Research |
| Audit trails                        | ✓          |
| Role-based permissions              | ✓          |
| Workflow management                 | ✓          |
| HR                                  | ✓          |
| Payroll                             | ✓          |
| Employee self-service               | ✓          |
| Payslips                            | ✓          |
| Leave management                    | ✓          |
| AI financial assistant              | **✓**      |
| Automated anomaly detection         | **✓**      |
| Financial lineage                   | **✓**      |
| Client-specific inventory workflows | **✓**      |

These are supported by the current Sage feature set, including inventory costing/serialisation, budgeting, workflow, audit trails, HR/payroll and reporting. ([Sage][1])

---

# 22. The First Major Architecture We Can See

The research is beginning to reveal this structure:

```text
                    SYNBOT FINANCIAL ECOSYSTEM
                              │
                 ┌────────────┴────────────┐
                 │                         │
          MASTER DATA                CONTROL ENGINE
                 │                         │
      ┌──────────┼──────────┐       Validation
      │          │          │       Approval
   Accounts   Customers   Vendors    Audit
      │          │          │       Permissions
      └──────────┼──────────┘
                 │
          TRANSACTION ENGINE
                 │
 ┌───────────────┼────────────────┐
 │               │                │
Sales/AR       AP/Procurement   Inventory
 │               │                │
 └───────────────┼────────────────┘
                 │
          ACCOUNTING ENGINE
                 │
        ┌────────┼────────┐
        │        │        │
       GL       AR/AP    Cash/Bank
        │        │        │
        └────────┼────────┘
                 │
        FINANCIAL STATEMENTS
                 │
    ┌────────────┼─────────────┐
    │            │             │
   P&L      Balance Sheet   Cash Flow
    │
    └────────────┬─────────────┘
                 │
          FINANCE INTELLIGENCE
                 │
       Finance AI / Analytics
```

And alongside it:

```text
             HR / STAFF
                 │
          Employee Master
                 │
      Attendance / Leave / Time
                 │
              PAYROLL
                 │
          Payroll Journal
                 │
         ACCOUNTING ENGINE
```

That last connection is particularly important.

**Payroll should not be a separate island.**

---

# 23. What We Have Learned So Far

The biggest conclusion from this first pass is that **Synbot Finance is actually four systems working as one**:

### 1. Accounting System

The books.

### 2. Operational Transaction System

Sales, purchasing, inventory, returns, loans, recalls, payments.

### 3. Workforce Financial System

HR, payroll, staff expenses, attendance and salary.

### 4. Financial Intelligence System

Dashboards, controls, forecasting, anomaly detection and AI.

That is much more ambitious—and much more appropriate—than simply rebuilding Sage 50.

---

# 24. Current Capability Map

If I consolidate the research into our working matrix:

| Domain                 | Target                           |
| ---------------------- | -------------------------------- |
| Accounting Core        | **CORE**                         |
| General Ledger         | **CORE**                         |
| Chart of Accounts      | **CORE**                         |
| Financial Statements   | **CORE**                         |
| AR                     | **CORE**                         |
| AP                     | **CORE**                         |
| Cash & Banking         | **CORE**                         |
| Bank Reconciliation    | **CORE**                         |
| Inventory              | **CORE**                         |
| Batch Management       | **CORE**                         |
| Recall                 | **CORE**                         |
| Stock Loans            | **CORE**                         |
| Returns                | **CORE**                         |
| Fixed Assets           | **CORE**                         |
| Payroll                | **CORE**                         |
| HR/Staff               | **CORE**                         |
| Budgeting              | **REQUIRED**                     |
| Expense Management     | **REQUIRED**                     |
| Audit                  | **CORE**                         |
| Internal Controls      | **CORE**                         |
| Permissions            | **CORE**                         |
| Reporting              | **CORE**                         |
| Financial Dashboard    | **CORE**                         |
| AI Finance Agent       | **ADVANCED**                     |
| Forecasting            | **ADVANCED**                     |
| Anomaly Detection      | **ADVANCED**                     |
| Multi-company          | **CORE for Synbot architecture** |
| Job Costing            | **RESEARCH**                     |
| Manufacturing/BOM      | **FUTURE/RESEARCH**              |
| Payroll/HR integration | **CORE**                         |
| Sage interoperability  | **REMOVED**                      |

---

## One important correction to our previous thinking

I would now **not call this the “Synbot Financial Core” alone**.

The research is pointing toward something bigger:

# **Synbot Financial Operating System**

Because the system isn't merely recording accounting transactions.

It will control the entire chain:

**Business Event → Operational Transaction → Accounting Event → Control → Ledger → Financial Statement → Intelligence**

For example:

**Customer buys vaccine**

→ Invoice
→ Batch recorded
→ Inventory decreases
→ COGS calculated
→ AR created
→ Revenue recognised
→ Customer credit limit checked
→ GL updated
→ Cash flow updated when paid
→ Customer ageing updated
→ Inventory history updated
→ Batch traceability maintained
→ P&L updated
→ Balance Sheet updated
→ Dashboard updated.

**One business event. One controlled transaction chain.**

That should become the fundamental philosophy of the eventual backend architecture.

---

## What I recommend we research next

I would **not move to backend/frontend documentation yet**.

The next research stage should be a much deeper **capability decomposition** of these major areas:

1. **Accounting engine & double-entry model**
2. **AR + Sales**
3. **AP + Procurement**
4. **Inventory + batch/recall/loan**
5. **Cash + bank reconciliation**
6. **Fixed assets**
7. **Payroll + HR**
8. **Budgeting**
9. **Internal accounting controls**
10. **Audit & compliance**
11. **Financial reporting**
12. **Financial intelligence/AI**
13. **Multi-company accounting**
14. **Permissions/workflows**

For each, we'll research **what Sage does → what the client actually needs → what Synbot should do → what Synbot should improve → required entities/data → required workflows → required reports**.

That becomes **Capability Matrix V2**, and from there we can produce the **Financial Workflow Map**.

Only after those two are complete should we freeze the database architecture and write the **backend + frontend development-engine documentation**.

That sequencing will reduce the risk of us designing a beautiful database around incomplete business rules.

[1]: https://www.sage.com/en-us/products/sage-50/features/?utm_source=chatgpt.com "Popular Sage 50 Features | Sage US"
[2]: https://www.sage.com/en-us/products/sage-50/?utm_source=chatgpt.com "Sage 50 Cloud Accounting Software for Small Business | Sage US"
[3]: https://www.sage.com/en-gb/products/sage-50-payroll/?utm_source=chatgpt.com "Sage 50 Payroll Software | Sage UK"
[4]: https://www.sage.com/en-us/products/sage-50/tax-ready/?utm_source=chatgpt.com "Tax season ready with Sage 50 Cloud Accounting | Sage US"
[5]: https://www.sage.com/en-gb/products/sage-50-accounts/?utm_source=chatgpt.com "Sage 50 Accounts - Finance Software | Sage UK"
[6]: https://www.sage.com/en-us/products/sage-50/pricing/?utm_source=chatgpt.com "Sage 50 Pricing Plans | Sage US"
