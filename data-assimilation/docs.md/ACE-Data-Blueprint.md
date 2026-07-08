# ACE Commercial Data Engineering Blueprint

**Version:** 1.0

**Platform:** ACE / Placeware Nigeria Limited

**Source System:** Sage 50 2013 (Peachtree)

**Prepared By:** Placeware Data Engineering

---

# Chapter 1 — Executive Summary & Vision

## ACE Commercial Data Platform

### 1.1 Purpose

This document defines the data engineering architecture for ACE (Placeware Nigeria Limited). It is the authoritative technical reference for how commercial and operational data is acquired, transformed, validated, stored, and analysed across the platform.

Unlike traditional ERP systems that focus on transactional record-keeping, ACE is designed as a **commercial intelligence platform**. Its objective is not only to record business activities, but to maintain an accurate, longitudinal representation of every commercial interaction while supporting operational efficiency, financial oversight, and future analytical capabilities.

This blueprint governs:

* Historical data migration from Sage 50
* Live operational data ingestion
* Commercial data normalisation
* Master Data Management (MDM)
* Data quality assurance
* Analytics and reporting
* API exposure
* Future AI integration

---

### 1.2 Project Background

ACE currently operates Sage 50 2013 (Peachtree) as its primary business management system. The legacy system stores years of valuable commercial history but exhibits limitations common to small-business accounting platforms:

* fragmented commercial information across proprietary binary tables,
* inconsistent use of master data (customers, products referenced by name rather than ID),
* limited historical normalisation,
* incomplete support for modern operational workflows,
* insufficient support for advanced reporting,
* minimal support for longitudinal commercial intelligence.

Rather than discarding historical information, ACE adopts a migration strategy that preserves legacy records while progressively enriching them through modern operational workflows.

---

### 1.3 Vision

The long-term vision for the ACE platform is to become a unified commercial intelligence system supporting the complete business lifecycle across:

* Customer Relationship Management (CRM)
* Inventory & Product Management
* Procurement & Vendor Management
* Financial Operations (AR, AP, GL)
* Revenue Cycle Management
* Business Intelligence & Analytics
* AI-assisted Commercial Operations

The database architecture must be designed for long-term evolution rather than short-term migration convenience.

---

### 1.4 Architectural Philosophy

One of the fundamental architectural decisions is that **customers are not the operational centre of the system**.

Customers are the subject of commerce.

**Transactions are the operational centre.**

Every commercial action — purchase order, sales invoice, payment, credit note, stock adjustment — belongs to a specific transaction. This transaction-centric architecture provides a complete commercial timeline while avoiding duplication of business information.

```text
Customer / Vendor
       ↓
  Transaction
       ↓
  Commercial Activities
       ↓
  Operational Activities
       ↓
     Analytics
```

---

### 1.5 Current Migration Status

At the time of writing, the ACE platform has successfully completed the initial migration of Sage 50 data into the Silver operational layer.

| Domain           | Imported Records |
| ---------------- | ---------------: |
| Customers        |              170 |
| Vendors          |               24 |
| Chart of Accounts|              204 |
| Products / Items |              174 |
| Inventory        |               58 |

Data quality assessment confirms zero duplicate account numbers and zero broken foreign-key relationships across the migrated tier-1 entities.

---

### 1.6 Data Engineering Objectives

**Objective 1 — Preserve Historical Integrity**
Every imported record retains source identifier, source system, synchronisation metadata, and audit timestamps.

**Objective 2 — Progressive Commercial Enrichment**
Historical data improves over time. Future transactions capture richer information that Sage never recorded.

**Objective 3 — Establish a Canonical Commercial Model**
One standardised representation of customers, vendors, products, transactions, GL accounts, payments, and staff — regardless of source.

**Objective 4 — Separate Operational and Analytical Workloads**
Operational tables serve low-latency transactional workflows. Gold layer serves aggregation and trend analysis.

**Objective 5 — Support Future Intelligence**
The database is structured for machine learning, predictive analytics, operational forecasting, and AI-assisted operations.

---

# Chapter 2 — Current State Assessment

### 2.1 System Overview

ACE is transitioning from a Sage 50 record-keeping environment to a full commercial intelligence platform. The platform integrates:

* Customer Management
* Product & Inventory Management
* Vendor & Procurement Management
* Financial Ledger (COA, AR, AP)
* Reporting & Intelligence
* AI Commercial Agents

---

### 2.2 Current Architecture

```text
                     Users
                        │
                        ▼
──────────────────────────────────────────────
  Frontend Applications (React / SynbotUI)
──────────────────────────────────────────────
           REST / Internal APIs (FastAPI)
──────────────────────────────────────────────
      Business Logic / Commercial Workflow
──────────────────────────────────────────────
         ACE Operational Database (PostgreSQL)
──────────────────────────────────────────────
            Bronze → Silver → Gold
──────────────────────────────────────────────
              Historical Sage 50 Data
```

---

### 2.3 Database Layers

**Bronze Layer** — Historical preservation. Immutable raw extracts. No business transformations. Full auditability.

**Silver Layer** — Operational commercial database. Normalised. Transactional. Used by live application.

**Gold Layer** — Business Intelligence. Denormalised, read-optimised, analytical. Powers dashboards and reporting.

---

### 2.4 Data Quality Assessment

Referential integrity: Excellent. Zero orphaned records. Zero broken foreign keys.

Identity coverage available: Account number, name, email, phone (partial).

Operational gaps: Transaction history (invoices/orders), payment events, GL amounts — these are post-launch enrichment goals, not migration failures.

---

### 2.5 Key Engineering Conclusions

1. The migration architecture is successful. Tier-1 entity data is imported with excellent relational integrity.
2. The remaining challenges are primarily semantic — missing reference data, metadata resolution, and transaction enrichment.
3. Master Data Management is the next architectural priority.
4. Live operations must focus on progressive enrichment through future transactions.

---

# Chapter 3 — Canonical Commercial Data Model

### 3.1 Introduction

The Canonical Commercial Data Model (CDM) establishes a single, authoritative representation of business information inside ACE, regardless of source system, import process, external integrations, API consumers, or reporting tools.

---

### 3.2 Architectural Philosophy

> **Everything that happens inside ACE belongs to a Transaction.**

Not a customer. Not a vendor. Not a product.

A Transaction.

Customers and vendors persist indefinitely. Transactions represent episodes of commercial activity. This distinction dramatically simplifies operational workflows.

---

### 3.3 The Seven Core Domains

**Domain 1 — Identity**
Customers, Vendors, Staff, Companies

**Domain 2 — Commercial**
Transactions (invoices, orders, credit notes), Line Items, Shipments

**Domain 3 — Inventory**
Products, Stock Movements, Batches, Expiry Records

**Domain 4 — Financial**
GL Accounts, Payments, Receipts, Adjustments, Reconciliations

**Domain 5 — Procurement**
Purchase Orders, Goods Received Notes, Vendor Payments

**Domain 6 — Revenue**
Sales Invoices, Collections, Credit Notes, Insurance Claims

**Domain 7 — Intelligence**
Dashboards, KPIs, Forecasts, AI Recommendations

---

### 3.4 Canonical Relationships

| Entity         | Parent          |
| -------------- | --------------- |
| Transaction    | Customer/Vendor |
| Line Item      | Transaction     |
| Payment        | Transaction     |
| Credit Note    | Transaction     |
| Stock Movement | Product         |
| GL Entry       | GL Account      |
| Batch Record   | Product         |

---

### 3.5 Canonical Design Rules

1. Every commercial action belongs to a Transaction.
2. Every Transaction belongs to exactly one Customer or Vendor.
3. Every operational table references master data where applicable.
4. No operational table stores duplicated business information.
5. Historical records are preserved and never destructively overwritten.
6. Workflow state is derived from recorded events, not mutable status fields alone.
7. Analytics consume canonical operational data, not raw imported structures.
8. APIs expose business objects rather than relational implementation details.
9. Every entity includes audit metadata (creator, timestamps, source system, modification history).
10. The canonical model takes precedence over Sage 50 source structures.

---

### 3.6 Canonical Metadata (every entity)

```text
id                  — UUID primary key
company_id          — which ACE company (planigli / plaphaen)
created_at
created_by
updated_at
updated_by
source_system       — "sage50" | "manual" | "api"
source_batch        — batch_id from ingestion run
source_key          — original Sage record identifier
is_active
version
```

---

# Chapter 4 — Master Data Management (MDM) Strategy

### 4.1 Why Master Data Matters

Without MDM, operational records accumulate inconsistencies:

```text
CARDIO SUPPLIES
Cardio Supplies Ltd
CARDIO SUPP
```

Three values — one vendor. The database treats them as different entities. Reports are wrong. Analytics are wrong. AI recommendations are unreliable.

MDM eliminates this by ensuring every record references a single, authoritative master entity.

---

### 4.2 ACE Master Data Domains

**Product Catalog** (items/drugs)
* item_code, description, unit_of_measure, category, cost_price, selling_price, vat_category, reorder_level, active_flag, legacy_sage_code

**Customer Master**
* account_no, name, credit_limit, payment_terms, region, status, contact_details

**Vendor Master**
* account_no, name, category, payment_terms, bank_details, status

**Chart of Accounts**
* gl_code, account_name, account_type (asset/liability/equity/revenue/expense), parent_code, active_flag

**Company Master**
* company_id (planigli, plaphaen), legal_name, registration_number, address, active_flag

---

### 4.3 MDM Principles

1. **Single Source of Truth** — every master entity exists only once.
2. **Reference, Don't Repeat** — store `product_id`, not "Amoxicillin 500mg".
3. **Master Data Evolves Slowly** — these datasets require governance, not transactional processing.
4. **Transactional Data Never Owns Reference Data** — products are never auto-created during a sales line item.
5. **Governance Before Growth** — new reference values require approval to prevent uncontrolled proliferation.

---

### 4.4 Data Stewardship

| Domain         | Steward               |
| -------------- | --------------------- |
| Product Catalog| Operations / Pharmacy |
| Customer Master| Sales / CRM           |
| Vendor Master  | Procurement           |
| Chart of Accounts| Finance / Accounts  |
| Company Master | Administration        |

---

# Chapter 5 — Data Quality Framework

### 5.1 Vision

> **Every commercial decision should be backed by trusted data.**

The platform must continuously answer:

1. Is the data complete?
2. Is the data correct?
3. Is the data internally consistent?
4. Can the data be traced to its origin?
5. Is the data useful for business operations?

---

### 5.2 The Seven Dimensions of Data Quality

**Dimension 1 — Completeness**
Required fields are present. Customer account_no, name: target ≥ 98%.

**Dimension 2 — Validity**
Values conform to expected formats. Prices must be positive. Account codes must match COA patterns.

**Dimension 3 — Consistency**
The same concept appears identically across the system. One customer record, referenced consistently everywhere.

**Dimension 4 — Accuracy**
Stored information reflects real-world business events.

**Dimension 5 — Referential Integrity**
Every foreign key resolves. Line items reference valid products. Transactions reference valid customers.

**Dimension 6 — Timeliness**
Information is recorded promptly. Inventory movements are documented at point of receipt.

**Dimension 7 — Traceability**
Every value answers: Who created it? When? From which source system? Which batch?

---

### 5.3 Quality Rules by Domain

**Customer**
- account_no required and unique
- name required
- status must be "active" or "inactive"

**Product / Items**
- item_id required
- cost_price ≥ 0
- selling_price ≥ 0
- is_active boolean

**Vendor**
- vendor_id required
- name required

**Chart of Accounts**
- account_id required
- account_name required
- account_type in {asset, liability, equity, revenue, expense, cost_of_goods}

---

### 5.4 Exception Severity Classification

**RECOVERABLE** — missing optional field, minor format issue → log and continue.

**DATA_QUALITY** — invalid format, unknown reference, duplicate key → quarantine record, notify steward.

**CRITICAL** — broken parent reference, corrupted source data, referential integrity violation → halt entity batch, require engineering review.

---

# Chapter 6 — ETL / Pipeline Architecture

### 6.1 Migration Philosophy

> **Historical data is migrated once. Operational data is created forever.**

The migration pipeline is finite. Once Sage 50 is fully replaced, the pipeline transitions to an operational data platform — ingesting new sources (bank feeds, e-commerce, logistics) without restructuring.

---

### 6.2 Pipeline Architecture

```text
Sage 50 (DAT binary files)
          │
          ▼
  Stage 1: Bronze Layer
  (raw, immutable, batched, timestamped)
          │
          ▼
  Stage 2: Data Quality Engine
  (validate, classify, quarantine failures)
          │
          ▼
  Stage 3: Canonical Transformation
  (map fields, normalise values, inject metadata)
          │
          ▼
  Stage 4: Master Data Resolution
  (resolve text names to governed IDs)
          │
          ▼
  Stage 5: Silver Layer
  (operational Synbot PostgreSQL)
          │
          ▼
  Stage 6: Gold Layer
  (analytics, KPIs, dashboards)
          │
          ├────────────────┐
          ▼                ▼
  Business Services    Analytics Platform
```

---

### 6.3 Stage Responsibilities

**Stage 1 — Bronze Layer**
Purpose: Preserve source information exactly as received. Immutable. Append-only. Source lineage retained. No business transformation. No cleansing.
Files: `sage50/extracted/bronze/<company>/<batch_id>/<entity>.json`

**Stage 2 — Data Quality Engine**
Validates: Completeness, Validity, Consistency, Uniqueness, Referential Integrity.
Returns: (valid_rows, quarantined_rows).
Failures are never silently discarded — every rejected row becomes a managed exception.

**Stage 3 — Canonical Transformation**
Maps Sage field names to canonical ACE names. Normalises values (status flags, currencies, dates). Injects source metadata (batch_id, source_system, source_key, company_id).

**Stage 4 — Master Data Resolution**
Replaces text references with governed identifiers. "Amoxicillin 500mg" → `item_id = ITM-0042`.

**Stage 5 — Silver Layer**
Operational PostgreSQL tables used by the live application. Fully normalised. Referential integrity enforced.

**Stage 6 — Gold Layer**
Denormalised, aggregated, reporting-optimised. Revenue KPIs, inventory performance, customer analytics.

---

### 6.4 Idempotency

Every migration operation must be safe to repeat. Running the same import twice produces the same operational result without creating duplicate business records.

Rules:
* Stable source identifiers (Sage account codes)
* Deterministic mapping logic
* Duplicate detection before insertion
* Merge or upsert where appropriate

---

### 6.5 Data Lineage

Every operational record must preserve provenance:

```text
Operational Record
        ↓
Canonical Mapped Record
        ↓
Bronze Raw Record
        ↓
Sage 50 Source Table
        ↓
Batch: batch_20260630_143012
```

Lineage metadata on every record:
* source_system = "sage50"
* source_batch = batch_id
* source_key = original Sage primary key
* company_id = "planigli" | "plaphaen"

---

### 6.6 Future Pipeline Evolution

Once Sage 50 is retired, the pipeline evolves to ingest:
* Bank statement feeds
* E-commerce orders
* Logistics tracking
* National tax authority filings

Each new integration requires only a Connector Adapter — the pipeline itself remains unchanged.

---

# Chapter 7 — Exception Management

### 7.1 Quarantine Queue

Failed records never disappear. Every quality failure becomes a managed exception in `exceptions.jsonl`.

Each exception record:
```json
{
  "batch_id":    "batch_20260630_143012",
  "company":     "planigli",
  "entity":      "customers",
  "source_key":  "CUST-00042",
  "error_type":  "MISSING_REQUIRED_FIELD",
  "field":       "account_no",
  "severity":    "DATA_QUALITY",
  "timestamp":   "2026-06-30T14:30:12Z",
  "raw_record":  {...}
}
```

### 7.2 Resolution Workflow

```text
Issue Detected
     ↓
Classification
     ↓
Severity Assignment
     ↓
Owner Assignment (data steward)
     ↓
Resolution
     ↓
Reprocessing
     ↓
Closure
```

### 7.3 Exception Categories

| Category              | Action                           |
| --------------------- | -------------------------------- |
| Missing optional field| Log + continue                   |
| Invalid format        | Quarantine + notify steward      |
| Duplicate key         | Quarantine + review              |
| Missing required field| Quarantine + notify steward      |
| Broken parent ref     | Halt entity batch + engineering  |
| Corrupted source data | Halt entity batch + engineering  |

---

# Chapter 8 — Persistence Architecture

### 8.1 Persistence Domains

```text
ACE PostgreSQL
│
├── integration   (SIF — Source connector metadata, batch logs, lineage)
├── master        (MDM — Customers, vendors, products, COA, companies)
├── registry      (Core instances — transactions, invoices, purchase orders)
├── workflow      (Workflow events, state transitions)
├── commercial    (Line items, deliveries, returns)
├── finance       (Payments, GL entries, reconciliations)
├── analytics     (Materialized views, KPIs, dashboards)
├── audit         (Immutable event log, config changes, access log)
└── security      (Users, roles, sessions, API keys)
```

### 8.2 Access Rules

No frontend component accesses persistence domains directly.

```text
PostgreSQL
     ↓
Repositories
     ↓
Domain Services
     ↓
Business Services
     ↓
API Layer (FastAPI)
     ↓
Frontend (React)
```

### 8.3 Database Engineering Standards

* UUID primary keys
* Foreign key enforcement
* Soft deletes (is_active flag)
* Audit metadata on all mutable entities
* Immutable event records (append-only)
* Indexed foreign keys and frequently queried columns
* Standard naming conventions (snake_case)
* Migrations managed through version-controlled SQL files

---

# Appendix — Domain Translation Reference

| Synbot Health (NL Blueprint)   | ACE / Placeware                        |
| ------------------------------ | -------------------------------------- |
| Hope HMS (legacy source)       | Sage 50 2013 (source system)           |
| Patient                        | Customer                               |
| Encounter                      | Transaction / Invoice / Order          |
| Clinical Activities            | Commercial Operations                  |
| Drug Formulary                 | Product / Items Catalog                |
| Laboratory Orders              | Purchase Orders                        |
| Prescriptions                  | Sales Orders                           |
| Billing / GL                   | GL Entries / Financial Transactions    |
| Staff                          | Employees                              |
| Departments                    | Business Units / Branches              |
| Insurance                      | Credit Terms / Payment Schedules       |
| MRN (Medical Record Number)    | Customer Account Number                |
| Encounter ID                   | Invoice / Transaction Number           |
| Bronze Layer                   | Bronze Layer (same concept)            |
| Silver Layer                   | Silver Layer (same concept)            |
| Gold Layer                     | Gold Layer (same concept)              |
| MDM                            | MDM (same concept, commercial domain)  |
| Clinical Workflow Engine       | Commercial Workflow Engine             |
| Clinical Lifecycle             | Transaction Lifecycle                  |
| SOAP Notes                     | Order Notes / Commercial Memos         |
| Laboratory Results             | Goods Received / Inspection Reports    |
| Dispensing                     | Delivery / Fulfilment                  |
| Triage                         | Order Prioritisation                   |
