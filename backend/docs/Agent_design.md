---

# **PROJECT PROMPT: SynBot Evolution → Departmental Intelligence & Workflow Automation Architecture**

## Objective

Transform SynBot from a tool-calling KPI assistant into a **structured, department-scoped intelligence system** that:

* Enhances Placeware Nigeria’s pharmaceutical cold-chain workflow
* Introduces domain-based Analyst Agents
* Implements closed-loop workflow automations
* Reduces DB inefficiencies via batched intelligence execution
* Preserves governance, auditability, and role-based boundaries
* Remains deterministic, scalable, and enterprise-safe

This is not an autonomous AI system.
This is a controlled intelligence upgrade.

---

# 1️⃣ Business Context (Operational Grounding)

Placeware Nigeria is a **regulated pharmaceutical cold-chain distributor**.

Core operational flow:

1. Port Clearing
2. Delivery to Warehouse (Anti-room)
3. Inventory + Quality Control (QC)
4. Cold Room Storage
5. NAFDAC Sampling & Regulatory Release
6. Invoicing (Based on Purchase Orders)
7. Packaging (Validated Temperature-Controlled Systems)
8. Delivery to Hospitals / Pharmacies / Patients

Key characteristics:

* High regulatory oversight (NAFDAC)
* Cold-chain dependency
* Batch & expiry tracking required
* PO-based B2B invoicing
* AR exposure risk
* Multi-stage inventory lifecycle
* Compliance-sensitive operations

The system must reflect and strengthen this workflow.

---

# 2️⃣ Architectural Upgrade Overview

Current Model:

```
Chat → Tool → DB Query → Compute → Return
```

New Model:

```
Chat → Domain Agent → Batch Fetch → Analyze → Structured Insight Object → Cache → Return
```

Agents must:

* Be domain-scoped
* Batch-fetch data
* Compute grouped metrics
* Produce structured outputs
* Write to TTL cache
* Be fully logged and auditable

No uncontrolled autonomy.
No self-triggering loops.
No agent spawning.

---

# 3️⃣ Core Architectural Additions

## A. Agent Framework Layer

Create `/agents/` directory.

### BaseAgent Interface

Each agent must implement:

* `collect_data()`
* `analyze()`
* `generate_insights()`
* `write_cache()`
* `get_output_schema()`

All agents return:

### Standard Insight Object

```
{
  metrics: {},
  findings: [],
  risks: [],
  recommendations: [],
  confidence_score: float,
  supporting_refs: [],
  execution_metadata: {
    query_count,
    latency,
    timestamp
  }
}
```

---

## B. Agent Registry

Create `agent_registry.py`.

Map:

* Agent Name
* Domain
* Required Role
* Trigger Context

Chat orchestration must call agents via registry.

---

## C. Batch Query Utility

Implement domain-level batch data fetch:

Instead of multiple DB calls per KPI:

Each agent:

* Performs grouped multi-table fetch
* Aggregates internally
* Writes summary to cache

Maintain TTL caching.

---

# 4️⃣ Departmental Agent Implementation

---

## 1. Import & Clearance Agent

Purpose:
Monitor shipment lifecycle and supplier performance.

Required Features:

* Shipment status tracking
* Clearance duration monitoring
* Delay threshold alerts
* Supplier reliability scorecard

Workflow Additions:
Shipment States:

* In Transit
* At Port
* Under Clearance
* Released
* Delivered

If clearance exceeds threshold:
→ Escalation log
→ Executive alert

---

## 2. Inventory Intelligence Agent

Purpose:
Closed-loop stock and batch lifecycle management.

Features:

### Low Stock Automation

If stock < threshold:
→ Auto-create Replenishment Recommendation
→ Add to Procurement Request Queue

When stock received:
→ Mark received
→ Update batch & expiry
→ Auto-clear alert

### Expiry Monitoring

If expiry < 60 days:
→ Flag risk
→ Recommend sales promotion or redistribution

### Cold Room Capacity

If storage > 85%:
→ Risk alert
→ Suggest redistribution

---

## 3. Compliance Monitoring Agent

Purpose:
Digitize regulatory enforcement logic.

Features:

* NAFDAC sampling status tracking
* Batch-level compliance states
* Lock invoice issuance for non-approved stock
* Audit export generation

If batch pending approval:
→ Prevent dispatch
→ Prevent invoice

Auto-release upon approval.

---

## 4. Cold-Chain Integrity Agent

Purpose:
Preserve temperature compliance across storage and dispatch.

Features:

* Temperature deviation logging
* Delivery box validation logging
* Van compliance tracking

If temperature breach:
→ Flag batch
→ Lock inventory
→ Notify QC

---

## 5. Logistics Optimization Agent

Purpose:
Improve delivery performance and SLA tracking.

Features:

* Dispatch lifecycle states
* Delivery delay detection
* SLA breach logging
* Route performance insights

If delay > threshold:
→ Notify operations
→ Log SLA breach
→ Feed Risk Agent

---

## 6. Financial Analyst Agent

Purpose:
Protect margin and credit exposure.

Features:

* AR aging risk scoring
* Product-line profitability
* Margin compression detection
* Currency impact simulation

If customer overdue > X days:
→ Flag credit risk
→ Reduce credit limit
→ Executive alert

---

## 7. Revenue Strategy Agent

Purpose:
Strategic growth planning.

Features:

* Accept growth goal input (e.g., +15% revenue)
* Decompose by:

  * Product mix
  * Pricing
  * Customer expansion
* Scenario simulation
* Weekly experiment proposals

Output:
Actionable growth roadmap.

---

## 8. Enterprise Risk Agent

Purpose:
Cross-domain risk consolidation.

Inputs:

* Regulatory signals
* Inventory pressure
* Financial exposure
* Logistics delays

Outputs:

* Risk heatmap
* Scenario projections
* Mitigation strategies

---

## 9. Business Process Optimization Agent

Purpose:
Detect workflow bottlenecks.

Monitors:

* Clearance duration
* Anti-room processing time
* Dispatch turnaround
* Invoice-to-payment cycle

Outputs:

* Bottleneck detection
* Process improvement suggestions

---

# 5️⃣ Workflow Automation Requirements

These must exist beyond agent analysis.

---

### Replenishment Lifecycle

Low stock → Request → Approval → PO → Delivery → Mark Received → Alert cleared

---

### Batch Compliance Lock

Pending approval → Cannot invoice → Auto-release upon approval

---

### Delivery Chain-of-Custody

Dispatch → Assign vehicle → Attach temp log → Delivery confirmation → Signed proof

---

### Credit Risk Enforcement

Overdue AR → Risk flag → Credit adjustment → Executive notification

---

### Expiry Prevention

Near expiry → Sales trigger → Redistribution suggestion

---

# 6️⃣ Executive Chat Upgrade

Chat must:

* Identify intent domain
* Route to relevant agent
* Merge multi-agent responses if cross-domain
* Summarize structured insight
* Display evidence references
* Maintain role boundaries

Replace granular tool planning for domain analytics.

---

# 7️⃣ Governance & Observability

Mandatory:

* Agent execution logs
* Query count tracking
* Cache hit/miss metrics
* Latency monitoring
* Role-based access enforcement
* Audit trail for all workflow state changes

---

# 8️⃣ Milestones

---

## Milestone 1 — Agent Framework Foundation

* BaseAgent class
* Agent registry
* Insight schema
* Batch query utility
* Logging layer

---

## Milestone 2 — Core Operational Agents

* Inventory Intelligence Agent
* Compliance Monitoring Agent
* Financial Analyst Agent

---

## Milestone 3 — Workflow Automation Engine

* Replenishment lifecycle
* Batch locking
* Delivery chain-of-custody
* Credit risk enforcement

---

## Milestone 4 — Strategic Layer

* Revenue Strategy Agent
* Enterprise Risk Agent
* Process Optimization Agent

---

## Milestone 5 — Executive Chat Integration

* Agent routing
* Multi-agent merging
* Structured report summarization

---

# 9️⃣ Success Criteria

System must:

* Reduce redundant DB calls
* Increase operational visibility
* Prevent compliance errors
* Detect risk earlier
* Automate inventory lifecycle
* Improve executive decision speed
* Maintain deterministic governance

---

# Final Vision

SynBot evolves into:

A structured digital operations & strategy intelligence layer
for regulated pharmaceutical distribution.

Not an experimental AI.
Not a dashboard tool.

A controlled, auditable, workflow-aware executive system.

---

End of implementation brief.
