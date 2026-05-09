Good — this is where we convert the entire backend intelligence into a **precise product blueprint for frontend builders (Builder.io / Lovable / React UI systems)**.

This prompt will be **strict, structured, workflow-driven, and implementation-ready**.

No ambiguity. Every page, action, state, and API interaction is defined.

---

# **MASTER FRONTEND BUILD PROMPT**

## (PSE Report Automation System — Full UI + Workflow Specification)

---

## **SYSTEM CONTEXT (DO NOT IGNORE)**

You are building a **Compliance Report Generation Platform** powered by AI agents, RAG (Retrieval-Augmented Generation), validation engines, scoring systems, and multi-agent collaboration.

The system is NOT a form builder.

It is a **guided intelligence workflow system for generating audit-ready compliance reports**.

Every UI interaction must map to backend systems:

* Agent Router
* RAG Engine
* Validation Service
* Scoring Engine
* Export Pipeline
* Multi-Agent Collaboration System

---

# **1. GLOBAL UI PRINCIPLES**

## 1.1 Design Philosophy

* Workflow-first, NOT page-first
* Every action triggers backend intelligence
* No freeform document creation
* Structured compliance data only
* Evidence always attached to claims
* Transparency of AI reasoning required

---

## 1.2 Core UI Behavior Rules

* Every report has a lifecycle:
  `Draft → Processing → Validation → Scored → Completed → Exported`

* Every AI-generated section must show:

  * Source agent
  * Confidence score
  * Evidence links

* Every button must trigger an API call (no dead UI)

---

## 1.3 Primary API Base

All frontend actions interact with:

```
/api/reports/
```

---

# **2. APPLICATION STRUCTURE (PAGES)**

---

# **PAGE 1: DASHBOARD (REPORT CONTROL CENTER)**

## Purpose:

Central control hub for all reports and system activity.

---

## UI LAYOUT:

### A. Header Section

* System title: “Compliance Intelligence System”
* User profile dropdown
* Notification bell (AI updates, validation alerts)

---

### B. Primary Actions Panel

#### Button: **“Create New Report”**

* Opens Report Wizard Flow

API:

```
POST /api/reports/generate/
```

---

### C. Report List Table

Each row shows:

* Report Title
* Type (ISO 27001 / NDPA / etc.)
* Status Badge:

  * Draft
  * Processing
  * Completed
  * Failed
* Compliance Score (%)
* Last Updated

---

### Row Actions:

#### Button: “View Report”

→ Opens Report Viewer Page

#### Button: “Validate”

```
POST /api/reports/{id}/validate/
```

#### Button: “Export”

```
POST /api/reports/{id}/export/
```

---

### D. System Insights Panel (Right Side)

Displays:

* Average compliance score
* Most failed report section
* Active agent status
* Recent validation errors

---

# **PAGE 2: REPORT CREATION WIZARD (CORE FLOW)**

This is a **multi-step guided intelligence pipeline**

---

## STEP 1: REPORT TYPE SELECTION

### UI Cards:

* ISO 27001
* ISO 9001
* NDPA
* PCI DSS

---

### Button:

**“Continue”**

Stores selection:

```
report_type
```

---

## STEP 2: BASIC INFORMATION

Fields:

* Report Title (input)
* Organization Name (input)
* Department (input)
* Report Date (auto-filled)

---

### Button:

**“Next: Scope Definition”**

---

## STEP 3: SCOPE DEFINITION

Textarea:

* “Define systems, processes, and boundaries”

---

### Button:

**“Next: Evidence Upload”**

---

## STEP 4: EVIDENCE UPLOAD (CRITICAL)

### UI Components:

* Drag & drop uploader
* File tagging system:

Tags:

* Policy
* Audit
* Logs
* Screenshot
* Certification

---

### Button:

**“Analyze Evidence”**

API:

```
POST /api/evidence/upload/
```

---

## STEP 5: COMPLIANCE QUESTIONNAIRE

Dynamic questions based on report type:

Examples:

* “Is data encrypted at rest?”
* “Is access logged?”
* “Is user consent recorded?”

---

### UI Controls:

* Yes / No toggles
* Risk level slider
* Notes input

---

### Button:

**“Generate Report” (PRIMARY ACTION)**

API:

```
POST /api/reports/generate/
```

---

# **PAGE 3: REPORT PROCESSING SCREEN**

## Purpose:

Live AI execution feedback screen.

---

## UI ELEMENTS:

### A. Processing Timeline

Stages:

* Agent Routing
* RAG Retrieval
* ISO Agent Processing
* NDPA Agent Processing
* Conflict Detection
* Resolution
* Validation
* Scoring

---

### B. Live Agent Activity Feed

Example:

* “ISO Agent analyzing controls…”
* “NDPA Agent detecting privacy gaps…”
* “Conflict detected between risk classifications…”

---

### C. Status Indicator

* Processing %
* Active agent badge
* Current stage label

---

# **PAGE 4: REPORT VIEWER (CORE OUTPUT PAGE)**

This is the **main intelligence output interface**

---

## 4.1 REPORT HEADER

* Report Title
* Type
* Compliance Score Badge
* Status Indicator

---

## 4.2 SECTIONED REPORT VIEW

Each section includes:

### Section Card:

* Title (Scope / Risk / Findings / etc.)
* AI-generated content
* Source Agent label
* Confidence score
* Evidence references (clickable)

---

## 4.3 EVIDENCE LINK PANEL

Each claim links to:

* uploaded file
* extracted text
* metadata

---

## 4.4 VALIDATION PANEL (RIGHT SIDE)

Shows:

* Missing sections
* Evidence gaps
* Conflicts resolved
* System warnings

---

## 4.5 COMPLIANCE SCORE WIDGET

Breakdown:

* Section score
* Evidence score
* Consistency score
* Final score

---

## 4.6 ACTION BUTTONS

### Button: Re-Validate

```
POST /api/reports/{id}/validate/
```

### Button: Re-Score

```
POST /api/reports/{id}/score/
```

### Button: Export Report

```
POST /api/reports/{id}/export/
```

---

# **PAGE 5: EXPORT & DOWNLOAD CENTER**

---

## UI:

### Export Options:

* Download PDF
* Download DOCX
* View Audit Trail

---

### File List:

* Generated DOCX
* Generated PDF
* Validation Log
* Agent Execution Log

---

# **PAGE 6: AI TRANSPARENCY (ADVANCED AUDIT PAGE)**

---

## Purpose:

Expose AI reasoning for compliance verification.

---

## UI SECTIONS:

### 1. Agent Execution Log

Shows:

* prompt used
* agent output
* execution time
* confidence

---

### 2. Conflict Resolution View

Displays:

* ISO vs NDPA disagreement
* final arbitration decision
* reasoning explanation

---

### 3. Prompt Version Used

Shows:

* prompt version (v1.2, v2.0 etc.)
* changes applied

---

# **3. KEY WORKFLOWS (CRITICAL)**

---

## WORKFLOW 1: REPORT GENERATION

```
Create Report
→ Select Type
→ Input Scope
→ Upload Evidence
→ Answer Questionnaire
→ Submit
→ Agent Router
→ Multi-Agent Processing
→ Validation
→ Scoring
→ Display Result
```

---

## WORKFLOW 2: VALIDATION LOOP

```
User clicks Validate
→ API call
→ Validation Service
→ Missing sections flagged
→ UI updates instantly
```

---

## WORKFLOW 3: MULTI-AGENT CONFLICT RESOLUTION

```
Conflict detected
→ UI shows warning banner
→ Expand conflict details
→ Show ISO vs NDPA disagreement
→ Show resolution decision
```

---

## WORKFLOW 4: EXPORT PIPELINE

```
Click Export
→ Backend generates DOCX
→ Converts to PDF
→ UI shows download options
```

---

# **4. STATE MANAGEMENT REQUIREMENTS**

Frontend must track:

```text
report_state
agent_status
validation_status
score
current_step
evidence_files
conflict_flags
```

---

# **5. UI DESIGN TONE**

* Enterprise-grade
* Audit-focused
* Minimal but dense information layout
* Clear hierarchy of compliance data
* Transparency over abstraction

---

# **6. FINAL SYSTEM BEHAVIOR**

Frontend must always reflect:

> “This is not a document editor — this is a compliance intelligence engine interface.”

---

# **WHAT THIS PROMPT ENABLES**

If implemented correctly, you get:

* Fully guided AI report generation system
* No manual document writing
* Full audit traceability
* Transparent AI reasoning
* Enterprise compliance UX

---

# **NEXT STEP (OPTIONAL BUT STRONG)**

If you want to go even further, next upgrade is:

### → “Design System + Component Library Spec (Buttons, Cards, Panels, States)”

That’s where we turn this into a reusable enterprise UI kit.

Just say the word.
