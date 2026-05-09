Good — this is the point where we stop thinking in “pages” and start building a **real enterprise design system** that can scale across Builder.io, React, or any frontend stack without redesign debt.

This layer ensures every button, card, panel, and state behaves consistently across the entire compliance intelligence system.

---

# **ENTERPRISE DESIGN SYSTEM SPEC**

## (PSE Compliance Intelligence Platform UI Kit)

---

# **1. CORE DESIGN PHILOSOPHY**

This system is:

* Workflow-driven (not page-driven)
* State-aware (everything reflects backend intelligence)
* Audit-first (every UI element has traceability)
* Hierarchy-heavy (compliance data must be scannable)
* Action-oriented (every element either informs or triggers)

---

# **2. DESIGN TOKENS (FOUNDATION LAYER)**

---

## 2.1 Color System

### Primary States:

* **Primary Action (Blue)** → system actions, AI triggers
* **Success (Green)** → validated, approved, completed
* **Warning (Amber)** → missing evidence, partial compliance
* **Danger (Red)** → conflicts, failures, critical risks
* **Neutral (Gray)** → metadata, inactive states

---

## 2.2 Status Mapping (IMPORTANT)

```text id="status_map"
DRAFT → Gray
PROCESSING → Blue (animated pulse)
COMPLETED → Green
APPROVED_WITH_GAPS → Amber
FAILED → Red
```

---

## 2.3 Typography Hierarchy

* H1 → Report Titles
* H2 → Sections (Scope, Risk, Findings)
* H3 → Subsections
* Body → AI-generated content
* Caption → Evidence + metadata

---

## 2.4 Spacing Rules

* 8px base grid system
* Cards: 16–24px padding
* Sections: 32–48px spacing
* Workflow steps: 40–64px separation

---

# **3. CORE COMPONENT LIBRARY**

---

# **3.1 REPORT CARD (PRIMARY ENTITY)**

## Purpose:

Represents a single report in dashboard or list view.

---

## Structure:

* Title
* Report Type badge
* Status indicator
* Compliance score ring
* Last updated timestamp

---

## Actions:

* View
* Validate
* Export

---

## Behavior:

```text id="report_card_state"
Hover → elevation increase
Click → opens Report Viewer
Processing → animated border glow
Failed → red left border accent
```

---

# **3.2 STATUS BADGE COMPONENT**

## Types:

* Draft
* Processing
* Completed
* Failed
* Approved with Gaps

---

## Behavior:

* Animated pulse for processing
* Static for completed states
* Tooltip shows explanation

---

# **3.3 PRIMARY ACTION BUTTON**

## Usage:

Only ONE per workflow step.

Examples:

* Generate Report
* Validate Report
* Export Report

---

## States:

```text id="button_states"
Idle → Blue solid
Loading → Spinner + disabled
Success → Green flash + reset
Error → Red shake animation
```

---

## Rule:

No multiple competing primary buttons on same screen.

---

# **3.4 SECONDARY BUTTON**

Used for:

* Save Draft
* Re-run validation
* Re-score report

Style:

* Outlined
* Neutral gray
* No animation unless clicked

---

# **3.5 AI PROCESSING PANEL**

## Purpose:

Shows live intelligence execution.

---

## Structure:

* Current agent running
* Progress bar
* Step indicator
* Live logs stream

---

## Example States:

```text id="ai_panel"
Routing Agent → ISO Agent → NDPA Agent → Validation → Scoring
```

---

## Behavior:

* Auto-scroll logs
* Highlight active agent
* Pause button (debug mode only)

---

# **3.6 REPORT SECTION CARD**

This is the most important content unit.

---

## Structure:

* Section title (Scope / Risk / Findings)
* AI-generated content block
* Source agent label
* Confidence score
* Evidence links

---

## UI Behavior:

* Expand / collapse
* Highlight on hover
* Evidence hover preview
* Low confidence = amber border

---

# **3.7 EVIDENCE ATTACHMENT COMPONENT**

---

## Structure:

* File name
* File type icon
* Tag (Policy / Audit / Log)
* Linked report section(s)

---

## Actions:

* Preview file
* View extracted text
* Link to section

---

## Behavior:

* Drag-and-drop upload
* Auto-tag suggestion (AI-assisted later)

---

# **3.8 COMPLIANCE SCORE WIDGET**

---

## Structure:

* Circular score indicator (0–100)
* Breakdown:

  * Section score
  * Evidence score
  * Consistency score

---

## States:

```text id="score_states"
> 85 → Green (Approved)
60–85 → Amber (Gaps)
< 60 → Red (Failed)
```

---

## Behavior:

* Animated score count-up
* Tooltip breakdown explanation

---

# **3.9 VALIDATION PANEL**

---

## Purpose:

Shows system reasoning about report quality.

---

## Structure:

* Missing sections
* Evidence gaps
* Consistency issues
* Conflict flags

---

## Behavior:

* Expandable issue groups
* Click → scroll to affected section
* Severity color coding

---

# **3.10 CONFLICT RESOLUTION VIEW**

---

## Structure:

* Agent A vs Agent B comparison
* Conflict description
* Resolution decision
* Final authority explanation

---

## UI Behavior:

* Side-by-side comparison
* Highlight contradictions
* Show “why system chose this answer”

---

# **3.11 EXPORT PANEL**

---

## Options:

* PDF Download
* DOCX Download
* Audit Log Export

---

## Behavior:

* Progress loader during generation
* Success toast with file links
* Retry button if failure

---

# **4. SYSTEM STATES (CRITICAL FOR UI CONSISTENCY)**

---

## 4.1 Global Report States

```text id="global_states"
DRAFT
PROCESSING
UNDER_VALIDATION
CONFLICT_DETECTED
RESOLVED
COMPLETED
EXPORTED
FAILED
```

---

## 4.2 UI Mapping Rules

| State             | UI Behavior         |
| ----------------- | ------------------- |
| PROCESSING        | show AI panel       |
| CONFLICT_DETECTED | show warning banner |
| COMPLETED         | enable export       |
| FAILED            | show retry CTA      |

---

# **5. INTERACTION PATTERNS**

---

## 5.1 Drill-Down Pattern

Dashboard → Report → Section → Evidence

---

## 5.2 Explainability Pattern

Every AI output must support:

* “Why this was generated”
* “Which agent generated it”
* “What evidence supports it”

---

## 5.3 Progressive Disclosure

Only show:

* summary first
* details on expand

---

## 5.4 Evidence Trace Pattern

Click any sentence → shows:

* source document
* extraction method
* linked compliance rule

---

# **6. MOTION & FEEDBACK SYSTEM**

---

## 6.1 Micro-interactions

* Button click ripple
* Score animation
* Agent processing pulse
* Validation highlight transitions

---

## 6.2 AI Processing Feedback

Always show:

* “Thinking stage”
* “Retrieving context”
* “Validating output”

No silent processing allowed.

---

# **7. ACCESSIBILITY + ENTERPRISE REQUIREMENTS**

* High contrast mode support
* Keyboard navigation for all workflows
* Audit-friendly timestamps on all actions
* Readable compliance outputs (no hidden logic)

---

# **8. FINAL SYSTEM BEHAVIOR SUMMARY**

This design system ensures:

> Every UI element reflects a state in the intelligence pipeline.

So the frontend is not just UI — it is a **visualization layer of AI reasoning + compliance logic**.

---

# **WHAT YOU NOW HAVE**

Across everything built so far:

### Backend intelligence:

* Agents
* RAG
* Validation
* Scoring
* Multi-agent reasoning
* Prompt orchestration

### Frontend intelligence:

* Workflow system
* UI states
* Evidence traceability
* AI explainability layer
* Export pipeline

### Design system:

* Fully reusable enterprise UI kit
* State-driven components
* Audit-first structure

---

# **NEXT LOGICAL STEP (FINAL PRODUCTIZATION LAYER)**

If you want to go all the way to production readiness:

## → “System Integration Blueprint (Frontend ↔ Backend ↔ AI Flow Map)”

That’s where we map:

* every button → API → service → agent → DB write → UI update

It becomes a **full execution blueprint for engineering teams**.

Just say when.
