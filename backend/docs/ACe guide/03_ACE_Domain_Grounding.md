# ACE Backend Research — Domain Grounding Pack

## A. RoyanHealth / Synbot Health

### Core data model

The current RoyanHealth database is organized into Bronze, Silver and Gold layers.

Silver contains structured operational clinical data including:
- patients,
- encounters,
- appointments,
- lab orders,
- prescriptions,
- billing.

Gold contains reporting-oriented dimensions and facts.

The patient table is the root of the clinical graph. Encounters connect to labs, prescriptions, billing and other clinical records.

### Known data-quality constraints

Current audit findings include:
- no broken foreign-key relationships across the audited paths;
- identity fields such as name, MRN, date of birth and gender are substantially complete;
- lab test names are a critical historical gap;
- encounter doctor, triage, ward/bed and discharge fields are largely absent from the imported Hope data;
- prescription records are high quality;
- payment method is not present in the Hope import;
- HMO/master data requires enrichment.

ACE must never convert a missing field into a clinical fact.

Example:
Bad: "The patient has no allergies."
Good: "No allergy information is available in the imported record."

### Clinical workflow language

The meeting notes indicate the operational flow revolves around:
- patient arrival,
- queue,
- initial assessment/vitals,
- doctor notes,
- orders,
- laboratory,
- pharmacy,
- billing,
- HMO,
- discharge.

ACE should use the organization's operational terminology rather than generic chatbot terminology.

### Clinical caution

ACE can:
- locate records,
- summarize documented information,
- explain workflow,
- surface missing information,
- report status,
- route users to the correct workflow.

ACE should not independently diagnose, prescribe, or invent clinical interpretation unless the deployment explicitly provides a validated clinical decision-support capability.

---

## B. Sage / Finance / Placeware-style deployments

### Accounting concepts

ACE should understand:
- General Ledger (GL),
- Profit and Loss (P&L),
- Balance Sheet,
- Accounts Receivable (AR),
- Accounts Payable (AP),
- inventory,
- cash flow,
- petty cash,
- journal,
- chart of accounts,
- depreciation,
- customer credit limits,
- inventory adjustment,
- stock reconciliation,
- batch tracking,
- recall,
- return inward,
- return outward.

### Client-specific accounting behaviour

The supplied Sage inventory shows the client uses extensive financial, inventory and reconciliation reports.

Held report families include:
- financial statements,
- general ledger,
- accounts receivable,
- accounts payable,
- inventory,
- account reconciliation.

Important missing reports identified in the current inventory:
- AP Cash Disbursements Journal,
- Inventory Adjustment Journal,
- Company Audit Trail,
- Working Trial Balance,
- selected additional financial statement reports.

ACE should distinguish between:
"report exists in Sage",
"report has been imported into ACE",
and
"report can be generated natively by ACE."

Never imply that a report is available in ACE simply because Sage supports it.

### Finance response style

Numbers first.

Example:
"Outstanding balance: ₦420,000.
The account has ₦100,000 in HMO coverage and ₦80,000 in recorded payments."

If a calculation is derived:
"Based on the recorded transactions..."

If a figure is missing:
"I can see the invoice, but I don't have the corresponding payment transaction."

---

## C. NeuroLayer / Synbot product doctrine

The platform is intended to support:
- modular chatbot modules,
- domain-specific agents,
- RAG,
- client-side data access,
- configurable personality,
- multi-tenant deployments,
- admin conversation logs,
- knowledge-base controls.

ACE should therefore be a reusable core, with domain packs layered on top.

Recommended model:

ACE Core
├── Conversation policy
├── Intent detection
├── Grounding policy
├── Response style
├── Safety
└── Evaluation

Domain Pack
├── terminology
├── entities
├── source hierarchy
├── workflows
├── tools
├── permissions
└── examples

Client Pack
├── company facts
├── current systems
├── business rules
├── user roles
└── source-of-truth mapping

This allows the same ACE engine to serve healthcare, pharma, finance, insurance and other Synbot deployments without contaminating one client's knowledge with another's.
