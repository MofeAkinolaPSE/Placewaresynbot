Good. We’ll go straight into **build-level design**, not theory.

---

# 🧱 PHASE 1 — ISO 27001 SYSTEM (LEAN + WORKING)

We are building **one complete loop**:

> Input → Validate → Generate → Export

---

# 1️⃣ CORE DATA MODEL (this is the foundation)

Everything depends on this. Keep it simple but structured.

### A. Standards Structure (from checklist)

```plaintext
Standard
- id (27001)
- name

Clause
- id
- standard_id
- title

Requirement
- id
- clause_id
- text
- action
- expected_evidence
- tag (mandatory/recommended)
```

---

### B. User Submission Layer

```plaintext
Project
- id
- name
- client
- date

Submission
- id
- project_id
- requirement_id
- status (not_started / in_progress / complete)
- comment

Evidence
- id
- submission_id
- file_url
- type (policy/log/etc)
- uploaded_at
```

---

### C. Derived Data (important for AI + reporting)

```plaintext
ComplianceScore
- project_id
- clause_id
- score (%)

Gap
- requirement_id
- issue
- severity
```

---

# 2️⃣ UI FLOW (what user actually does)

### Screen 1: Report Selection

* ISO 27001

---

### Screen 2: Project Setup

* Project name
* Client
* Scope

---

### Screen 3: Checklist Interface (CORE UI)

This is your uploaded checklist converted into UI:

For each requirement:

* ✅ Checkbox (status)
* 📎 Upload evidence
* 💬 Comment
* 📌 Tag (auto)

---

### Screen 4: Validation View

System shows:

* Missing evidence
* Incomplete sections
* Risk level

---

### Screen 5: Generate Report

* Button: “Generate ISO 27001 Report”

---

### Screen 6: Preview + Export

* Editable sections
* Export to DOC/PDF

---

# 3️⃣ VALIDATION ENGINE (keep it rule-based first)

No AI yet here. Keep it deterministic.

### Rules:

* If `mandatory` + no evidence → ❌ FAIL
* If incomplete → ⚠️ GAP
* If complete → ✅ OK

---

### Output:

```plaintext
Requirement → Status:
- Compliant
- Partially Compliant
- Non-Compliant
```

---

# 4️⃣ ISO 27001 AGENT (FIRST AGENT DESIGN)

This is where AI comes in.

### Input to agent:

```json
{
  "project_info": {...},
  "compliance_data": [...],
  "evidence_summary": [...],
  "gaps": [...]
}
```

---

### What the agent does:

Generates **structured report sections**:

1. Introduction
2. Scope
3. Methodology
4. Findings
5. Risk / Gap Analysis
6. Recommendations

---

### Key design rule:

> Agent does NOT guess — it only works from structured data

---

# 5️⃣ OUTPUT ENGINE (very simple)

No AI here.

### Responsibilities:

* Take structured sections
* Insert into template
* Export:

  * DOCX
  * PDF

---

# 6️⃣ END-TO-END FLOW (THIS IS YOUR FIRST WORKING SYSTEM)

```plaintext
User fills checklist + uploads evidence
        ↓
System stores structured data
        ↓
Validation Engine runs
        ↓
Gaps + scores generated
        ↓
ISO 27001 Agent runs
        ↓
Generates report sections
        ↓
Output Engine formats
        ↓
User downloads report
```

---

# 7️⃣ MINIMAL STACK (DO NOT OVERBUILD)

### Backend

* Django (fast, structured, admin ready)

### Database

* PostgreSQL (or even SQLite for V1)

### File Storage

* Local or S3-compatible

### AI

* API-based (no custom model yet)

### Frontend

* Builder.io (since you already use it)
  OR simple React if needed

---

# 8️⃣ WHAT WE ARE NOT BUILDING (YET)

* ❌ Multi-agent orchestration
* ❌ Full RAG pipeline
* ❌ All ISO standards
* ❌ Complex scoring models

---

# 🎯 DELIVERABLE OF PHASE 1

A user should be able to:

1. Select ISO 27001
2. Fill checklist
3. Upload evidence
4. Click generate
5. Download a structured compliance report

---

# 🚀 NEXT STEP (very important)

We now zoom into:

👉 **Checklist → Database mapping (actual implementation)**
👉 OR
👉 **ISO 27001 Agent prompt design (how it thinks and writes)**

Pick one:

* **“Data mapping”** (backend-first)
* **“Agent design”** (AI-first)

Both connect, but we build cleaner if we go step-by-step.
