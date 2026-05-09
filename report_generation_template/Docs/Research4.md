Perfect—now we design the **actual brain** of the system.

This is not just a prompt, this is a **controlled generation system** that ensures:

* no hallucination
* structured outputs
* audit-ready consistency

---

# 🧠 ISO 27001 AGENT — PROMPT ARCHITECTURE (BUILD SPEC)

We’ll design this in **layers**, so it’s modular and easy to evolve.

---

# 1️⃣ AGENT ROLE (SYSTEM LAYER)

This is fixed. It defines identity + boundaries.

```plaintext
You are an ISO 27001 Compliance Auditor and Report Generator.

Your role is to:
- Analyze structured compliance data
- Evaluate completeness and gaps
- Generate audit-ready report sections

You must:
- Only use provided data
- Not assume missing information
- Clearly flag non-compliance
- Maintain formal, professional audit tone
```

---

# 2️⃣ INPUT CONTRACT (STRICT JSON)

The agent ONLY accepts structured input.

```json
{
  "project_info": {
    "name": "",
    "client": "",
    "scope": ""
  },
  "clauses": [
    {
      "clause_id": "5.1",
      "title": "Leadership and Commitment",
      "requirements": [
        {
          "requirement_id": "5.1.1",
          "text": "...",
          "status": "compliant | partial | non_compliant",
          "evidence": ["policy_doc.pdf"],
          "comment": ""
        }
      ]
    }
  ],
  "gaps": [
    {
      "requirement_id": "5.1.1",
      "issue": "Missing formal policy",
      "severity": "high"
    }
  ],
  "compliance_summary": {
    "overall_score": 72,
    "per_clause": {
      "5": 80,
      "6": 60
    }
  }
}
```

---

# 3️⃣ OUTPUT CONTRACT (VERY IMPORTANT)

We do NOT allow free-form output.

Agent must return:

```json
{
  "introduction": "",
  "scope": "",
  "methodology": "",
  "findings": [
    {
      "clause": "5",
      "summary": "",
      "status": ""
    }
  ],
  "gap_analysis": [
    {
      "issue": "",
      "impact": "",
      "severity": ""
    }
  ],
  "recommendations": [
    {
      "recommendation": "",
      "priority": ""
    }
  ],
  "conclusion": ""
}
```

---

# 4️⃣ CORE REASONING FLOW (HOW AGENT THINKS)

This is embedded in the prompt as instructions.

---

### Step 1: Interpret Compliance

* Read clause → evaluate statuses
* Determine:

  * compliant
  * partially compliant
  * non-compliant

---

### Step 2: Generate Findings

For each clause:

* Summarize performance
* Mention strengths
* Highlight weaknesses

---

### Step 3: Analyze Gaps

For each gap:

* Explain issue
* Explain impact (risk)
* Keep it audit-style (not casual)

---

### Step 4: Recommendations

* Must directly map to gaps
* Must be actionable
* Must be realistic

---

### Step 5: Conclusion

* Summarize overall posture
* Reference compliance score
* State readiness level

---

# 5️⃣ HARD RULES (ANTI-HALLUCINATION)

This is critical.

```plaintext
- Do NOT invent policies, documents, or evidence
- If evidence is missing → explicitly state it
- If data is incomplete → reflect uncertainty
- Do NOT generalize beyond input data
- Keep statements traceable to inputs
```

---

# 6️⃣ SECTION GENERATION STRATEGY

We control tone per section:

---

### Introduction

* Context + purpose
* No assumptions

---

### Scope

* Derived ONLY from project_info.scope

---

### Methodology

* Fixed template:

  * checklist-based
  * evidence review
  * compliance evaluation

---

### Findings

* Clause-by-clause
* Balanced (strength + weakness)

---

### Gap Analysis

* Risk-focused
* Severity-aware

---

### Recommendations

* Clear action steps
* No vague advice

---

### Conclusion

* Executive summary
* Decision-ready

---

# 7️⃣ PROMPT TEMPLATE (WHAT WE ACTUALLY SEND TO MODEL)

This is your backend payload:

```plaintext
[SYSTEM ROLE]

{agent_role}

---

[INSTRUCTIONS]

Follow the reasoning process:
1. Evaluate compliance per clause
2. Generate findings
3. Analyze gaps
4. Provide recommendations
5. Conclude overall compliance

Strictly follow output JSON format.

---

[INPUT DATA]

{structured_json}
```

---

# 8️⃣ WHY THIS WORKS (IMPORTANT)

This design ensures:

* ✅ Deterministic outputs (not random essays)
* ✅ Easy frontend rendering
* ✅ Easy DOC/PDF formatting
* ✅ Future RAG integration (clean)
* ✅ Multi-agent scaling later

---

# 9️⃣ WHAT WE’VE JUST UNLOCKED

You now have:

* A **standardized AI brain**
* That can be reused for:

  * ISO 22301
  * ISO 9001
  * ISO 20000

Only thing that changes:

* Input data
* Clause structure

---

# 🚀 NEXT STEP (CRITICAL DECISION)

We now connect this to reality:

Choose one:

### 🔹 Option A — “Backend Wiring”

* Convert this into Django endpoints
* Build API → agent call → response handling

### 🔹 Option B — “UI + Checklist Binding”

* Turn ISO checklist into actual working interface
* Connect form → structured JSON

---

If we do this right, within the next step:

> you’ll have your **first working AI-generated ISO report** (even if rough)

Pick your direction.
