Below is the **backend system architecture directive** for implementing the **Synbot Compliance & Audit Automation Upgrade (V1)** for Placeware.
This is written intentionally like a **build prompt / technical instruction** so a backend engineer or agent can implement it directly.

---

# Synbot V1 Upgrade

## Compliance Automation System — Backend Architecture Directive

### Objective

Extend Synbot from a conversational system into a **Quality Management System (QMS) automation platform** capable of:

1. Automating internal audits
2. Tracking SOP compliance
3. Detecting missed operational schedules
4. Generating deviation reports automatically
5. Managing calibration and maintenance schedules
6. Generating product recall documentation
7. Generating structured compliance reports on demand

The system must rely primarily on **structured operational data**, not AI hallucination.

AI is used for **interpretation, summarization, and conversational interaction**, while **reports are generated from deterministic data templates**.

---

# 1. High Level System Architecture

System Structure:

```
Client UI
   │
Synbot Chat Interface
   │
Executive Orchestration Service (EOS)
   │
Operational Agent Layer
   │
Compliance Data Layer
   │
Document Generation Engine
   │
Export / Reporting Interface
```

---

# 2. Executive Orchestration Service (EOS)

EOS is the **central orchestration service** responsible for interpreting user commands and delegating tasks to internal agents.

EOS responsibilities:

• Parse user intent
• Determine which agent executes the task
• Retrieve required operational data
• Trigger report generation pipelines
• Return final output to the user

Example command:

```
"Generate February Self Audit"
```

EOS workflow:

```
Intent Parser
      ↓
Audit Agent
      ↓
Database query
      ↓
Document generator
      ↓
Return formatted report
```

---

# 3. Operational Agent Layer

Create the following backend agents as independent services/modules.

---

## Agent 1 — Audit Intelligence Agent

Purpose:

Automate internal audits based on the **Audit Universe schedule**.

Functions:

• Track audit calendar
• Notify when audits are due
• Generate audit reports
• Store audit findings

Primary dataset:

```
audit_schedule
audit_type
risk_level
frequency
month_due
status
report_document
```

Example EOS trigger:

```
generate_audit_report(month="February")
```

Output:

Structured audit report identical to the **Fumigation Audit document format**.

---

## Agent 2 — Compliance Monitoring Agent

Purpose:

Continuously verify that SOP-driven activities occur on schedule.

Tracked activities include:

• fumigation
• training
• vaccine storage inspection
• sanitation checks
• cold chain verification

Dataset structure:

```
activity_name
sop_reference
scheduled_date
completion_date
status
responsible_staff
```

Compliance logic:

```
if completion_date > scheduled_date:
    flag_non_compliance
```

When triggered:

```
send alert
trigger deviation engine
```

---

## Agent 3 — Deviation & CAPA Engine

Purpose:

Automatically generate **Deviation Investigation Reports** when operational failures occur.

Example trigger:

```
maintenance_missed
audit_not_completed
inspection_failed
```

Deviation report fields:

```
deviation_id
investigation_start_date
observation
classification
impact_assessment
recommendations
responsible_department
```

The report format must replicate the **existing deviation document structure**.

Deviation detection pipeline:

```
schedule_monitor
      ↓
missed_event
      ↓
deviation_engine
      ↓
generate_deviation_report
```

---

## Agent 4 — Maintenance & Calibration Tracker

Purpose:

Track maintenance and calibration for equipment used in vaccine storage.

Tracked equipment:

• refrigerators
• cold rooms
• temperature monitoring devices
• generators

Dataset structure:

```
equipment_id
equipment_type
location
maintenance_interval
last_maintenance
next_maintenance
certificate_document
status
```

System behavior:

```
daily maintenance scan
if next_maintenance - today < 7 days:
    send notification
```

---

## Agent 5 — Product Recall Manager

Purpose:

Generate product recall documentation and trace distribution history.

Required datasets:

```
product_batch
delivery_records
customer_distribution
storage_records
```

Example command:

```
generate_product_recall(batch_number)
```

System output:

• Recall Notice
• Recall Investigation Report
• Distribution Trace Report

All fields populated using system data.

No AI-generated assumptions allowed.

---

# 4. Compliance Data Layer

Primary database:

```
PostgreSQL
```

Extensions:

```
pgvector (for RAG indexing)
```

Core tables:

```
sop_registry
audit_schedule
compliance_activity_log
maintenance_schedule
equipment_registry
deviation_reports
recall_cases
document_archive
```

All operational activities must be logged.

---

# 5. Document Generation Engine

All compliance reports must use **structured templates**, not free-form AI generation.

Templates required:

```
audit_report_template
deviation_report_template
recall_report_template
maintenance_report_template
```

Workflow:

```
user request
      ↓
data retrieval
      ↓
populate template
      ↓
generate document
```

Supported output formats:

• PDF
• DOCX
• Excel

---

# 6. Knowledge Retrieval Layer (RAG)

Purpose:

Allow Synbot to answer SOP-related questions.

Data indexed:

• SOP documents
• audit reports
• deviation reports
• maintenance logs

Embedding storage:

```
pgvector
```

Example query:

```
"What is the SOP for vaccine transport?"
```

Pipeline:

```
query
↓
vector search
↓
retrieve relevant SOP sections
↓
LLM response
```

---

# 7. Data Ingestion Layer

Primary external source:

```
Sage ERP
```

Data ingestion methods:

1. CSV export ingestion
2. Excel ingestion
3. API ingestion (if available)
4. Manual data entry UI

Goal:

Allow operational data to enter Synbot even if Sage integration is limited.

---

# 8. Export and Reporting Interface

Users must be able to export generated documents.

Supported export formats:

```
PDF
DOCX
Excel
CSV
```

Example commands:

```
Export deviation report
Export audit report
Download recall documentation
```

---

# 9. Synbot Command Interface

Synbot acts as the **command layer for the entire system**.

Example commands:

```
Generate February Self Audit
Show upcoming calibrations
Create deviation report
Generate product recall report
Show compliance dashboard
```

EOS interprets these commands and routes to appropriate agents.

---

# 10. Security & Role Access

User roles:

```
Administrator
Quality Assurance
Operations
Management
```

Access rules:

• only QA can generate deviation reports
• only management can approve audit reports
• operations can log activities

-

---

# 11. Version Strategy

## Version 1

Operational automation:

• audit automation
• compliance monitoring
• deviation generation
• maintenance tracking
• recall reporting
• RAG for SOPs

---

---

# Final Design Summary

Synbot becomes a **Compliance Operating System**.

Capabilities:

• run audits automatically
• monitor SOP compliance
• detect operational failures
• generate regulatory documents
• maintain maintenance schedules
• assist staff with SOP knowledge

This architecture ensures **maximum reliability, minimal hallucination, and strong operational value**.

---

 finally design the (very important)** is the **database schema for the compliance system**.

That schema will determine **80% of how powerful Synbot becomes** for this client.
