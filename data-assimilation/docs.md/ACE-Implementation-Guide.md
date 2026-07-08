# ACE Commercial Distribution Platform
# Data Implementation Guide

## Engineering Specification — Version 1.0

---

# Purpose

This document translates the architectural principles defined in the **ACE Data Engineering Blueprint** into concrete implementation guidance for the ACE engineering team.

Where the blueprint defines *why* the ACE data platform is built the way it is, this guide defines *exactly what to build, in what order, and how to verify it is correct*.

It is the authoritative engineering reference for implementing the ACE data pipeline, canonical commercial model, master data layer, business services, and operational readiness standards.

---

# Intended Audience

- Data Engineers (pipeline implementation)
- Backend Engineers (business services, API layer)
- Database Engineers (persistence domains)
- Solution Architects (integration design)
- Technical Leads (implementation governance)

---

# Guiding Principles

Every implementation decision must align with the architectural principles established in the ACE Data Engineering Blueprint:

- **Chapter 2** — Current State Assessment
- **Chapter 3** — Canonical Commercial Data Model
- **Chapter 4** — Master Data Management
- **Chapter 5** — Data Quality Framework
- **Chapter 6** — Pipeline Architecture
- **Chapter 7** — Exception Management

Where implementation choices conflict with Sage 50's data structure, the ACE canonical architecture takes precedence.

---

# Document Structure

| Chapter | Purpose |
|---------|---------|
| 1 | Current State Assessment |
| 2 | Canonical Commercial Model Implementation |
| 3 | Master Data Engineering |
| 4 | Data Engineering & Quality Pipeline |
| 5 | Integration Architecture |
| 6 | Persistence Architecture |
| 7 | Business Service Layer |
| 8 | Transaction Lifecycle Architecture |
| 9 | Commercial Intelligence Layer |
| 10 | Operational Readiness & Continuous Operations |

Each chapter concludes with: Engineering Decisions, Implementation Requirements, Acceptance Criteria, Developer Checklist.

---

# Chapter 1

# Current State Assessment

## Purpose

Before designing the target implementation, the engineering team must establish a clear understanding of the current operational environment.

The objective is not to reproduce Sage 50 within Synbot, but to identify the information assets, operational workflows, and data quality considerations that must be preserved, transformed, or enhanced during ingestion.

---

## 1.1 Current Environment

ACE operates two pharmaceutical distribution companies:

- **planigli** — primary distribution entity
- **plaphaen** — secondary pharmaceutical entity

Both companies run Sage 50 as their accounting and inventory management system.

The current information footprint extracted from Sage 50:

| Entity | Count | Notes |
|--------|-------|-------|
| customers | ~170 | Primary commercial entity |
| vendors | ~24 | Supplier master |
| chart_of_accounts | ~204 | GL structure |
| items | ~174 | Product catalog |
| stock_on_hand | ~58 | Inventory position (synthesized) |
| **Total** | **~289** | Across both companies |

---

## 1.2 Findings from the Data Assessment

### Observation 1 — Sage 50 is application-centric

Information is organized around Sage 50 modules rather than enterprise commercial entities.

Customers, vendors, items, and GL accounts are stored in separate flat structures with no explicit transactional relationships represented.

### Observation 2 — Transactional data is not yet accessible

Sales invoices, purchase orders, and GL journal entries exist in Sage 50 but require additional extraction work.

These are Tier-2 entities scheduled for Phase 2.

### Observation 3 — Reference data is inconsistent across companies

Item descriptions, account names, and vendor identifiers may differ between planigli and plaphaen for the same real-world concept.

Master data resolution must reconcile these across company boundaries.

### Observation 4 — No lineage exists in the current state

Raw Sage 50 data flows directly to the Synbot backend with no audit trail, quality gate, or canonical transformation.

---

## 1.3 Gap Assessment

| Gap | Description | Status |
|-----|-------------|--------|
| Bronze Layer | Immutable raw archive | **Implemented** |
| Quality Engine | Validation + quarantine | **Implemented** |
| Canonical Mapper | Field mapping + metadata | **Implemented** |
| Exception Manager | Severity-classified log | **Implemented** |
| Master Resolution | Reference → ID resolution | **Stage 4 — This sprint** |
| Commercial Intelligence | Knowledge objects + dashboards | **Phase 2** |
| Transaction Lifecycle | Invoice/order workflow | **Phase 2** |
| Gold Layer Analytics | KPI materialized views | **Phase 2** |

---

## 1.4 Target Architecture

```
Sage 50 (DAT files / CSV exports)
        │
        ▼
Stage 1 — Bronze Layer (raw, immutable, batched)
        │
        ▼
Stage 2 — Data Quality Engine (validate, quarantine failures)
        │
        ▼
Stage 3 — Canonical Transformation (field mapping + metadata)
        │
        ▼
Stage 4 — Master Data Resolution (text refs → governed IDs)
        │
        ▼
Stage 5 — Silver Layer (Synbot operational DB via FastAPI)
        │
        ▼
Stage 6 — Gold Layer (analytics, KPIs) [Phase 2]
```

The frontend and business services interact exclusively with the Silver layer.

---

## Engineering Decisions

- Sage 50 is a source system, not the target architecture
- The canonical commercial model replaces Sage 50's application-centric structures
- Master data governance precedes operational ingestion
- Business services become the official backend contract; raw tables are never exposed directly

## Implementation Requirements

The engineering team shall:

1. Profile every Sage 50 entity and document its canonical commercial meaning
2. Map all entities to the ACE Canonical Commercial Model
3. Establish Master Data repositories before transactional entity migration
4. Implement Bronze, Quality, Canonical, Master Resolution, and Silver stages
5. Preserve source lineage for every ingested record
6. Log every exception with classification and severity

## Acceptance Criteria

- Every Sage 50 entity has a documented canonical mapping
- Pipeline stages are implemented and tested
- All ingested records carry source lineage metadata
- Exception log captures all failures with classification

## Developer Checklist

- [x] Bronze layer implemented (`bronze_layer.py`)
- [x] Quality engine implemented (`quality_engine.py`)
- [x] Canonical mapper implemented (`canonical_mapper.py`)
- [x] Exception manager implemented (`exception_manager.py`)
- [ ] Master resolver implemented (`master_resolver.py`)
- [ ] Batch reporter implemented (`batch_reporter.py`)
- [ ] assimilate.py updated with Stage 4

---

# Chapter 2

# Canonical Commercial Model Implementation

## Purpose

The purpose of this chapter is to define the implementation of the ACE Canonical Commercial Model (CCM).

The Canonical Commercial Model is the authoritative enterprise representation of commercial distribution information within ACE/Synbot.

All source systems — including Sage 50, CSV exports, and future ERP integrations — must transform information into this canonical model before operational processing.

---

## 2.1 Engineering Objective

The backend must not expose Sage 50 entities directly.

Every imported record shall be translated into a canonical commercial entity.

This provides:

- Consistent business APIs
- Stable frontend contracts
- AI-ready commercial context
- Multi-company scalability
- Source system independence

---

## 2.2 Canonical Transformation Architecture

Every record follows the same lifecycle:

```
Sage 50 Source Record
        │
        ▼
Structural Mapping (field names + types)
        │
        ▼
Semantic Normalisation (status flags, string cleanup)
        │
        ▼
Source Metadata Injection (source_system, source_batch, source_key, company_id)
        │
        ▼
Master Data Resolution (text references → governed IDs)
        │
        ▼
Canonical Commercial Object
        │
        ▼
Silver Layer (Synbot operational DB)
```

No operational record should bypass this process.

---

## 2.3 Canonical Entity Catalogue

### Customer

Represents a business that purchases from ACE.

Contains:
- Customer Account Number (unique identifier)
- Company Name
- Contact Information
- Credit Limit
- Payment Terms
- Status (active / inactive)
- Source lineage metadata

---

### Vendor

Represents a supplier from whom ACE purchases.

Contains:
- Vendor Account Number
- Company Name
- Payment Terms
- Category
- Status
- Source lineage metadata

---

### Item (Product)

Represents a product in the ACE pharmaceutical catalog.

Contains:
- Item Code (unique identifier)
- Item Name / Description
- Unit of Measure
- Category
- Cost Price
- Selling Price
- Status (active / inactive)
- Source lineage metadata

---

### Chart of Accounts (COA)

Represents the financial account structure.

Contains:
- Account Code (unique identifier)
- Account Name
- Account Type (asset / liability / equity / revenue / expense)
- Parent Account
- Status
- Source lineage metadata

---

### Stock Position

Represents current inventory levels.

Contains:
- Item Reference
- Quantity on Hand
- Quantity on Order
- Reorder Level
- Company ID
- Source lineage metadata

---

### Transaction *(Phase 2)*

Represents a commercial event (sale, purchase, stock movement).

Contains:
- Transaction Number
- Transaction Type (sales / purchase / transfer)
- Customer or Vendor Reference
- Date
- Line Items
- Total Value
- Status

---

## 2.4 Canonical Relationships

```
Customer / Vendor
        │
        ▼
Transaction (Invoice / Order)
        │
        ▼
Line Items
        │
        ▼
Item (Product Reference)
        │
        ▼
Financial Events (payment, credit, adjustment)
        │
        ▼
GL Entries (Chart of Accounts)
```

Every relationship is represented through governed references, never duplicated values.

---

## 2.5 Canonical Metadata Standard

Every canonical entity inherits:

```
id
company_id
source_system       "sage50"
source_batch        batch_20260630_143012
source_key          original Sage 50 primary key
created_at
updated_at
is_active
version
```

These fields enable governance, auditing, lineage, and future multi-company expansion.

---

## 2.6 Transformation Rules

### Structural Transformation

Maps Sage 50 field names and types to canonical names.

Example:

```
CustId  →  customer_id
CustName  →  name
```

### Semantic Transformation

Standardizes business meaning.

Example:

```
"Y", "1", "TRUE", "ACTIVE", "A"
        ↓
"active"
```

### Business Transformation

Applies enterprise rules using Master Data.

Example (Phase 2):

```
"customer_name = ALHAJI MUSA PHARMA"
        ↓
customer_id = "CUST-0042"
```

---

## 2.7 Commercial Context Object

The backend should assemble complete commercial contexts rather than exposing raw entities.

```json
CompanyCommercialContext {
  "company": { "id": "planigli", "name": "Planigli Ltd" },
  "customers": [...],
  "vendors": [...],
  "inventory": [...],
  "outstanding_invoices": [...],
  "financial_position": { "payables": 0, "receivables": 0 },
  "data_confidence_score": 1.0
}
```

This object powers the company dashboard and AI analysis.

---

## Engineering Decisions

- The Canonical Commercial Model is the authoritative enterprise data model
- Sage 50 source structures are implementation details and shall not influence frontend contracts
- All transformations occur before operational persistence
- Business services and APIs consume canonical entities exclusively

## Implementation Requirements

1. Define canonical entity classes for every commercial concept
2. Build transformation adapters for Sage 50 entities
3. Implement structural, semantic, and business transformation stages
4. Apply validation before persistence
5. Maintain source lineage metadata on every record

## Acceptance Criteria

- Every Sage 50 entity maps to one or more canonical commercial entities
- Canonical entities are independent of Sage 50 naming and structure
- Validation rules prevent invalid operational data from entering production
- Source lineage is traceable from every record back to its Sage 50 origin

## Developer Checklist

- [x] `canonical_mapper.py` — structural + semantic transformation
- [x] `field_maps.py` — field-level mapping definitions
- [x] Source metadata injection (`source_system`, `source_batch`, `source_key`, `company_id`)
- [ ] Business transformation (Master Resolution) — `master_resolver.py`
- [ ] Commercial Context assembly — Phase 2

---

# Chapter 3

# Master Data Engineering

## Building the ACE Commercial Source of Truth

---

## Purpose

Master Data represents the authoritative reference information used across every commercial operation within ACE.

Unlike transactional information — which changes with every order — Master Data defines the stable commercial concepts upon which the enterprise depends.

ACE Master Data examples:
- Product Catalog (what ACE sells)
- Customer Master (who ACE sells to)
- Vendor Master (who ACE buys from)
- Chart of Accounts (how ACE accounts for it)
- Company Master (which entity owns the activity)

Every operational workflow, API, and report should reference Master Data rather than storing duplicated descriptive information.

---

## 3.1 Engineering Objective

Establish a single commercial source of truth for every reusable business concept.

Master Data eliminates:
- Duplicated item descriptions across companies
- Inconsistent customer naming
- Conflicting account identifiers
- Semantic ambiguity between planigli and plaphaen

---

## 3.2 ACE Master Data Domains

```
ACE Master Data
        │
        ├── Commercial (products, customers, vendors)
        ├── Financial (chart of accounts, payment terms)
        ├── Operational (stock positions, reorder rules)
        └── Enterprise (company definitions, branches)
```

---

## 3.3 Product Catalog

The authoritative pharmaceutical product reference.

Fields:
- `item_id` — immutable identifier
- `item_name` — canonical description (normalised)
- `aliases` — alternative names used in Sage 50
- `unit_of_measure`
- `category` (pharmaceutical / equipment / consumable)
- `cost_price`
- `selling_price`
- `active`
- `version`

Governance rule: a new drug can only enter the product catalog through an approved business operation, not a direct database insert.

---

## 3.4 Customer Master

Fields:
- `customer_id` — immutable identifier
- `account_no` — Sage 50 account number (unique per company)
- `name`
- `contact`
- `credit_limit`
- `payment_terms`
- `status`
- `company_id`
- `version`

---

## 3.5 Vendor Master

Fields:
- `vendor_id` — immutable identifier
- `account_no` — Sage 50 vendor number
- `name`
- `payment_terms`
- `category`
- `status`
- `company_id`
- `version`

---

## 3.6 Chart of Accounts

Fields:
- `account_id` — immutable identifier
- `account_code` — Sage 50 GL code
- `account_name`
- `account_type` (asset / liability / equity / revenue / expense)
- `parent_account`
- `status`
- `company_id`
- `version`

---

## 3.7 Company Master

Defines each operating entity:

| Company ID | Name | Description |
|------------|------|-------------|
| planigli | Planigli Ltd | Primary distribution entity |
| plaphaen | Plaphaen Ltd | Secondary pharmaceutical entity |

---

## 3.8 Duplicate Resolution

Migration from Sage 50 will discover inconsistencies in naming across companies.

Example:

```
"AMOX 500MG"
"Amoxicillin 500mg"
"AMOXICILLIN CAPSULE 500MG"
```

These may represent a single product. The resolution strategy:

1. Extract all item descriptions from both companies
2. Apply normalisation (lowercase, collapse whitespace)
3. Flag likely duplicates for steward review
4. Map aliases to the canonical product record
5. The canonical record carries the governed name; aliases remain searchable

---

## 3.9 Master Data Lifecycle

```
Proposed
        ↓
Validated
        ↓
Active
        ↓
Deprecated
        ↓
Archived
```

Deletion is prohibited. Historical records must remain valid.

---

## 3.10 Master Resolution in the Pipeline

Stage 4 of the ACE pipeline (implemented in `master_resolver.py`) performs in-batch resolution.

At current scale:
- Cross-company consistency checks
- `company_id` validation against the Company Master
- `account_type` validation against the COA type vocabulary
- Future: resolve item_name → item_id when transactional entities arrive

---

## Engineering Decisions

- Master Data is the commercial source of truth for ACE
- Every transactional entity references Master Data by identifier
- Sage 50 reference values are normalised during ingestion
- Business ownership resides with the operations team; technology enforces governance

## Implementation Requirements

1. Create master repositories in the Synbot DB
2. Implement immutable identifiers for every master entity
3. Build duplicate detection for item descriptions across companies
4. Expose governed APIs for all reference domains
5. Introduce soft deactivation with version tracking

## Acceptance Criteria

- Every operational record references a governed master entity
- Item duplicates across planigli and plaphaen are consolidated
- Alias mappings preserve historical Sage 50 compatibility
- APIs retrieve reference information from the master repository

## Developer Checklist

- [ ] `master_resolver.py` — Stage 4 in-batch resolution
- [ ] Master tables populated in Synbot DB (backend team)
- [ ] Alias mapping table created
- [ ] Company Master defined

---

# Chapter 4

# Data Engineering & Quality Pipeline

## Engineering Trusted Commercial Information

---

## Purpose

The purpose of this chapter is to define the enterprise data engineering pipeline responsible for transforming Sage 50 data into trusted commercial information suitable for ACE/Synbot operations.

The objective is not simply to import data. The objective is to establish trusted commercial information.

---

## 4.1 Pipeline Architecture

```
Sage 50 (DAT files / CSV exports)
                │
                ▼
        Stage 1 — Bronze Landing Layer
                │
                ▼
        Stage 2 — Data Quality Engine
                │
                ▼
        Stage 3 — Canonical Transformation
                │
                ▼
        Stage 4 — Master Data Resolution
                │
                ▼
        Stage 5 — Operational Database (Synbot)
                │
                ▼
        Stage 6 — Commercial Intelligence [Phase 2]
                │
           ┌────┴────┐
           ▼         ▼
  Business Services  Analytics Platform
```

---

## 4.2 Stage 1 — Bronze Landing Layer

**File:** `bronze_layer.py`  
**Status:** Implemented

Purpose: Preserve source information exactly as received.

Characteristics:
- Immutable — never modified after write
- Append-only — each batch creates new files
- Source lineage retained — batch_id, company, entity, extraction_timestamp
- No business transformation
- No cleansing

Storage: `sage50/extracted/bronze/<company>/<batch_id>/<entity>.json`

The Bronze archive is the legal and technical record of what was extracted from Sage 50.

---

## 4.3 Stage 2 — Data Quality Engine

**File:** `quality_engine.py`  
**Status:** Implemented

Validation categories:

| Category | Examples |
|----------|---------|
| Completeness | `customer_id` required, `item_id` required |
| Validity | `account_type` in valid set, price ≥ 0 |
| Uniqueness | Duplicate `customer_id` within batch |
| Referential Integrity | Item reference exists in item catalog |

Severity classification:

| Severity | Meaning | Action |
|----------|---------|--------|
| RECOVERABLE | Minor issue, optional field | Log + include |
| DATA_QUALITY | Invalid format, duplicate key | Log + quarantine |
| CRITICAL | Broken reference, corrupted data | Log + halt entity batch |

---

## 4.4 Stage 3 — Canonical Transformation

**File:** `canonical_mapper.py`  
**Status:** Implemented

Responsibilities:
- Field name + type mapping via `field_maps.map_row()`
- Semantic normalisation (status flags, string cleanup)
- Source metadata injection per record

Output: canonical commercial objects ready for Master Resolution and Silver upload.

---

## 4.5 Stage 4 — Master Data Resolution

**File:** `master_resolver.py`  
**Status:** This sprint

Responsibilities:
- Validate `company_id` against Company Master
- Validate `account_type` against COA type vocabulary
- Flag unresolved references as RECOVERABLE exceptions
- Future: resolve text names to governed IDs once transactional entities arrive

Returns `(resolved_rows, unresolved_results)`.

Unresolved rows are logged to `exception_manager` but included in the upload (RECOVERABLE severity).

---

## 4.6 Stage 5 — Silver Layer (Operational Database)

**File:** `assimilate.py` (upload section)  
**Status:** Implemented (via FastAPI POST to Synbot backend)

Only records that have passed Stages 1–4 are uploaded to the Synbot operational database.

---

## 4.7 Exception Management

**File:** `exception_manager.py`  
**Status:** Implemented

Exception log: `exceptions.jsonl` (append-only)

Every exception entry carries:
```json
{
  "timestamp": "2026-06-30T14:30:12Z",
  "batch_id": "batch_20260630_143012",
  "company": "planigli",
  "entity": "customers",
  "error_type": "MISSING_REQUIRED_FIELD",
  "field": "customer_id",
  "severity": "DATA_QUALITY",
  "raw_record": { ... }
}
```

---

## 4.8 Data Quality Metrics

| Metric | Target |
|--------|--------|
| Completeness (required fields) | ≥ 99% |
| Canonical mapping success | ≥ 99% |
| Master resolution success | ≥ 95% |
| Exception resolution SLA | Weekly steward review |

---

## 4.9 Data Lineage

Every operational record preserves full provenance:

```
Synbot Customer Record
        ↓
Canonical Customer Object
        ↓
Sage 50 Customer Row
        ↓
Bronze Archive
        ↓
batch_20260630_143012
```

This lineage supports audits, troubleshooting, and migration verification.

---

## 4.10 Incremental Ingestion

The pipeline supports repeatable execution.

- Running the same batch twice produces identical results (idempotent)
- Bronze archive: skips if file already exists (`bronze_layer.save()` is idempotent)
- Silver layer: backend PATCH/PUT handles upserts

---

## Engineering Decisions

- Ingestion is a governed data engineering pipeline, not a table copy exercise
- Quality validation precedes canonical transformation
- Canonical entities reference governed Master Data
- Every record preserves lineage from source to operational state
- All stages run for every entity; no stage can be skipped silently

## Implementation Requirements

1. Bronze Landing: immutable, batched, idempotent
2. Quality Engine: configurable per-entity rules, no silent failures
3. Canonical Mapper: structural + semantic + metadata
4. Master Resolver: validates cross-entity references, logs RECOVERABLE exceptions
5. Exception Manager: severity-classified, append-only log
6. Silver upload: upsert via FastAPI, retry on transient failure

## Acceptance Criteria

- All imported data passes through all 5 stages before reaching operational tables
- Validation failures are isolated, classified, and traceable
- Canonical transformation is consistent across all ingested entities
- Exception log captures every failure with severity and raw record
- Full lineage is available from every operational record back to Sage 50

## Developer Checklist

- [x] Stage 1 (`bronze_layer.py`)
- [x] Stage 2 (`quality_engine.py`)
- [x] Stage 3 (`canonical_mapper.py`)
- [x] Exception management (`exception_manager.py`)
- [ ] Stage 4 (`master_resolver.py`)
- [ ] Stage 4 integration in `assimilate.py`
- [ ] Data Confidence Score in batch summary

---

# Chapter 5

# Integration Architecture

## Engineering a Reusable ACE Integration Layer

---

## Purpose

The pipeline built for Sage 50 ingestion shall not be implemented as a one-time migration utility. It shall become a reusable ACE Integration Layer capable of connecting multiple source systems through standardized transformation pipelines.

---

## 5.1 ACE Source Connectors

| Connector | Source | Status |
|-----------|--------|--------|
| Sage50Connector | Binary DAT files via `hard_reader.py` | Implemented |
| CSVConnector | Manual Sage exports via `assimilate_from_csv.py` | Implemented |
| ExcelConnector | Future manual imports | Phase 2 |
| ERPConnector | Future REST API integration | Phase 3 |

Each connector:
- Extracts only — no business logic, no canonical mapping
- Produces standardized raw records with extraction metadata
- Never writes directly to operational schemas

---

## 5.2 Connector Responsibilities

Each connector shall:
- Establish connection to the source system
- Extract source records
- Preserve source metadata (extraction timestamp, entity name, company)
- Package records into standardized ingestion messages

Connectors shall never:
- Modify business data
- Perform canonical mapping
- Apply Master Data rules
- Implement workflow logic

---

## 5.3 Integration Contract

Every connector produces a standardized batch payload:

```json
{
  "connector": "sage50",
  "entity": "customers",
  "company": "planigli",
  "batch_id": "batch_20260630_143012",
  "extraction_timestamp": "2026-06-30T14:30:12Z",
  "row_count": 140,
  "rows": [ ... ]
}
```

This is what `bronze_layer.save()` archives.

---

## 5.4 Idempotent Processing

Every pipeline run is idempotent:
- Bronze save skips if `<batch_id>/<entity>.json` already exists
- Silver upload uses upsert (not insert) semantics
- Running the same batch twice produces the same operational result

This is essential for recovery and restart scenarios.

---

## 5.5 Batch Management

Every ingestion belongs to a governed batch:

```
batch_id
        ↓
Source system + entity
        ↓
Extraction timestamp
        ↓
Records extracted
        ↓
Records valid
        ↓
Records canonical
        ↓
Records resolved
        ↓
Exceptions
        ↓
Batch status
```

Batch history is queryable via `batch_reporter.py`.

---

## 5.6 Exception Queue

Failed records enter the exception queue (`exceptions.jsonl`) rather than disappearing.

Each entity's exception sub-queue supports:
- Investigation (what failed and why)
- Correction (fix source data)
- Reprocessing (re-run after correction)
- Auditing (historical exception record)

---

## Engineering Decisions

- Ingestion is implemented as a reusable integration capability, not a one-time script
- Connectors perform extraction only; business logic resides in pipeline stages
- Integration contracts standardize communication between connectors and pipeline stages
- Domain events will support loose coupling in future (Phase 2 event bus)

## Implementation Requirements

1. Maintain clear separation between connector (extract) and pipeline (transform/load)
2. All connectors produce the same standardized batch payload structure
3. Bronze archive serves as the connector output record
4. Idempotent processing for all ingestion operations
5. Exception queue captures all unresolvable records

## Acceptance Criteria

- Sage 50 binary ingestion and CSV ingestion follow the same pipeline architecture
- Connectors can be replaced without affecting pipeline stages
- Batches are fully traceable and restartable
- Failed records are captured in the exception log

## Developer Checklist

- [x] Sage50Connector (`sage50/hard_reader.py`)
- [x] CSVConnector (`assimilate_from_csv.py`)
- [x] Batch management (`batch_id` generation in `assimilate.py`)
- [x] Bronze archive as connector output
- [x] Exception log as failure capture
- [ ] `batch_reporter.py` for batch history

---

# Chapter 6

# Persistence Architecture

## Engineering the ACE Operational Foundation

---

## Purpose

The ACE operational database is organized around commercial capabilities, not application modules.

Each persistence domain represents a cohesive business responsibility with clearly defined ownership, lifecycle, and access patterns.

---

## 6.1 ACE Persistence Domains

```
Synbot PostgreSQL
        │
        ├── integration     (pipeline batches, exceptions, lineage)
        ├── master          (product catalog, customer master, COA, company)
        ├── commercial      (transactions, line items, stock positions)
        ├── financial       (invoices, payments, GL entries)
        ├── analytics       (KPI views, materialized aggregates) [Phase 2]
        ├── audit           (pipeline events, API events, changes)
        └── configuration   (company settings, pipeline config)
```

---

## 6.2 Integration Domain

**Framework Owner:** ACE Integration Layer

**Purpose:** Receives and stages information from external systems.

**Example Entities:**
- `integration_batches` — batch_id, status, row counts
- `source_records` — raw records with lineage
- `migration_exceptions` — exception log mirror
- `lineage_records` — record-level provenance

**Lifecycle:** Short-lived operational metadata with long-term audit retention.

---

## 6.3 Master Domain

**Purpose:** Stores commercial reference information.

**Example Entities:**
- `products` (item catalog)
- `customers` (customer master)
- `vendors` (vendor master)
- `chart_of_accounts`
- `companies`

**Characteristics:**
- Versioned
- Governed
- Low write frequency
- High read frequency
- Soft delete only

**Access:** Read by every business service. Modified only through governed workflows.

---

## 6.4 Commercial Domain

**Purpose:** Stores commercial operational records.

**Example Entities:**
- `transactions` (sales / purchase / transfer)
- `transaction_lines`
- `stock_positions`
- `stock_movements` [Phase 2]

**Note:** Transactions reference Master domain by ID, never by duplicated text.

---

## 6.5 Financial Domain

**Purpose:** Stores financial operations.

**Example Entities:**
- `invoices`
- `payments`
- `gl_entries`
- `payment_allocations`
- `financial_adjustments`

**Rule:** Financial history is immutable once finalised. Corrections use adjustment transactions, not destructive updates.

---

## 6.6 Access Model

```
PostgreSQL
        ↓
Repositories
        ↓
Domain Services
        ↓
Business Services
        ↓
Commercial Intelligence Services [Phase 2]
        ↓
API Layer
        ↓
Frontend / Dashboard
```

No frontend component accesses persistence domains directly.

---

## 6.7 Database Engineering Standards

All persistence domains shall conform to:
- UUID or governed string primary keys
- Foreign key enforcement
- Soft deletes on master entities
- Audit metadata on mutable entities
- Indexed foreign keys
- Standard naming conventions
- Version control for all schema migrations

---

## Engineering Decisions

- Persistence is organized around commercial capabilities, not Sage 50 tables
- Master Data is governed independently of operational transactions
- Financial history is immutable
- Analytics remains isolated from operational processing

## Implementation Requirements

1. Create PostgreSQL schemas aligned with the defined persistence domains
2. Implement repositories for each domain
3. Separate domain services from persistence logic
4. Enforce foreign key relationships between commercial and master domains
5. Apply standardized engineering practices across all schemas

## Acceptance Criteria

- All database schemas align with commercial persistence domains
- Master and commercial domains are physically separated
- Business services encapsulate rules; repositories handle persistence only

## Developer Checklist

- [ ] `integration` schema + repositories (backend team)
- [ ] `master` schema + repositories (backend team)
- [ ] `commercial` schema (backend team)
- [ ] `financial` schema (backend team)
- [x] Pipeline writes to Synbot via FastAPI (existing upload in `assimilate.py`)

---

# Chapter 7

# Business Service Layer

## Engineering Commercial Capabilities Instead of CRUD Services

---

## Purpose

Business Services are the operational implementation of ACE's commercial capabilities.

Rather than exposing database entities or CRUD operations, Business Services encapsulate commercial rules, transaction coordination, validation, and governance.

Every service should answer: **"What commercial capability does this provide?"** Not: "Which table does this update?"

---

## 7.1 ACE Business Capabilities

### ProductCatalogService

Responsibilities:
- Register new pharmaceutical products
- Update product information (governed)
- Manage product lifecycle (active → deprecated → archived)
- Expose product search and formulary lookup

Publishes: `ProductRegistered`, `ProductUpdated`, `ProductDeprecated`

---

### CustomerAccountService

Responsibilities:
- Register customers
- Manage credit terms and limits
- Update account status
- Retrieve customer commercial context

Publishes: `CustomerRegistered`, `CustomerUpdated`, `CreditLimitChanged`

---

### VendorManagementService

Responsibilities:
- Register vendors
- Manage vendor payment terms
- Update vendor status

Publishes: `VendorRegistered`, `VendorUpdated`

---

### InventoryService

Responsibilities:
- Update stock positions
- Record stock movements
- Trigger reorder alerts

Publishes: `StockPositionUpdated`, `ReorderAlertTriggered`

---

### FinancialOperationsService

Responsibilities:
- Post GL entries
- Generate invoices
- Process payments
- Reconcile accounts

Publishes: `InvoiceCreated`, `PaymentReceived`, `GLEntryPosted`

---

### CommercialIntelligenceService

Responsibilities:
- Assemble CompanyCommercialContext
- Generate CustomerAccountContext
- Produce InventoryIntelligence objects

Consumes knowledge objects from the Intelligence Layer.

---

## 7.2 Service Architecture

```
API Request
        ↓
Controller (protocol adapter only)
        ↓
Business Service (orchestrates)
        ↓
Domain Service (validates rules)
        ↓
Repository (persistence abstraction)
        ↓
Persistence Domain
```

Business logic never lives in controllers or repositories.

---

## 7.3 Business View Models

Business services return curated commercial contexts:

- `CompanyCommercialContext`
- `CustomerAccountContext`
- `InventoryIntelligence`
- `FinancialPosition`
- `OperationsDashboard`

View models are optimized for business workflows, not database normalization.

---

## Engineering Decisions

- Business services implement commercial capabilities, not CRUD operations
- Domain services encapsulate reusable business rules
- Repositories remain persistence-only
- Business services coordinate across persistence domains
- Domain events are published after successful business operations

## Implementation Requirements

1. Organize services around commercial capabilities
2. Separate orchestration from domain validation
3. Return view models tailored to business workflows
4. Publish domain events after successful transactions

## Acceptance Criteria

- Business services align with commercial capabilities, not database tables
- Domain logic is reusable across APIs, integrations, and dashboards
- Controllers contain no significant business logic

## Developer Checklist

- [ ] `ProductCatalogService` (backend team)
- [ ] `CustomerAccountService` (backend team)
- [ ] `VendorManagementService` (backend team)
- [ ] `InventoryService` (backend team)
- [ ] `FinancialOperationsService` (backend team)
- [ ] `CommercialIntelligenceService` (backend team — Phase 2)

---

# Chapter 8

# Transaction Lifecycle Architecture

## Engineering Commercial Operations as Executable Workflows

---

## Purpose

Commercial operations are not isolated API calls. They are coordinated business processes with defined lifecycle states, validation rules, and audit requirements.

This chapter defines the Transaction Lifecycle Architecture — the ACE equivalent of the NL Enterprise Orchestration Engine.

---

## 8.1 ACE Transaction Lifecycles

### Purchase Cycle

```
Purchase Order Created
        ↓
Goods Received Note Raised
        ↓
Vendor Invoice Matched
        ↓
Payment Processed
        ↓
GL Entry Posted
        ↓
Reconciled
```

### Sales Cycle

```
Sales Order Created
        ↓
Stock Reserved
        ↓
Delivery Note Raised
        ↓
Sales Invoice Issued
        ↓
Payment Received
        ↓
GL Entry Posted
        ↓
Reconciled
```

### Stock Movement

```
Movement Initiated
        ↓
Stock Deducted (source location)
        ↓
Stock Added (destination location)
        ↓
Movement Confirmed
        ↓
GL Entry Posted
```

---

## 8.2 Lifecycle Governance

Every lifecycle transition must satisfy:

- State preconditions (cannot invoice an undelivered order)
- Authorization requirements (who can approve each stage)
- Audit event generation (every transition is recorded)
- Knowledge update trigger (company context is refreshed)

---

## 8.3 Implementation Notes

The Transaction Lifecycle Architecture is **Phase 2** work.

Prerequisites:
- Sales invoices and purchase orders must be accessible from Sage 50 (Tier-2 entities)
- Master Data must be fully populated and governed
- Business services must be operational

Current engineering milestone: establish the foundation (master data, canonical model, quality pipeline) that the lifecycle engine will consume.

---

## Engineering Decisions

- Transaction lifecycles replace ad-hoc API calls with governed business processes
- Every lifecycle transition generates an audit event
- Transitions are validated against business policies before execution
- Knowledge objects are updated asynchronously following each transition

## Acceptance Criteria (Phase 2)

- Purchase cycle, sales cycle, and stock movement execute as governed workflows
- Every transition is auditable with full business context
- Lifecycle policies prevent invalid state transitions

## Developer Checklist

- [ ] Tier-2 entity extraction from Sage 50 (jrnlhdr, jrnlrow, stxhdr, stxrow)
- [ ] Transaction canonical model
- [ ] Purchase lifecycle workflow
- [ ] Sales lifecycle workflow
- [ ] Stock movement lifecycle

---

# Chapter 9

# Commercial Intelligence Layer

## Engineering Enterprise Knowledge for Commercial Operations

---

## Purpose

The purpose of this chapter is to define how ACE/Synbot transforms operational commercial information into intelligence that can be consumed consistently across the platform.

Operational systems record facts. Intelligence systems explain meaning.

Example:

```
Operational Data
        │
customers[], vendors[], items[], stock_positions[]

        ↓

Commercial Intelligence

        │
CompanyCommercialContext {
  financial_position: "₦4.2M receivables, ₦1.8M payables",
  inventory_health: "3 items below reorder level",
  top_customers: [...],
  data_confidence_score: 0.98
}
```

---

## 9.1 ACE Commercial Intelligence Objects

### CompanyCommercialContext

The company-level operational picture. Powers the main dashboard.

Contains:
- Company profile
- Active customer count + credit utilization
- Inventory position summary
- Outstanding payables + receivables
- Top 10 customers by value
- Stock alerts (below reorder level)
- Data Confidence Score

---

### CustomerAccountContext

Complete commercial context for a specific customer.

Contains:
- Customer profile
- Outstanding invoice balance
- Credit utilization
- Order history (last 12 months)
- Payment performance
- Active credit holds

---

### InventoryIntelligence

Product and stock intelligence.

Contains:
- Items below reorder level
- Slow-moving items (no sales in 90 days)
- High-value stock (top 20% by cost)
- Stock valuation by category
- Expiry risk items [pharmaceutical-specific]

---

### FinancialPosition

GL and financial summary.

Contains:
- Payables aging
- Receivables aging
- GL account balances by type
- Month-on-month comparison

---

## 9.2 Data Confidence Score

The Data Confidence Score (DCS) is the ACE adaptation of the NL Trust Score. It quantifies how much confidence the system has in the completeness and accuracy of the current data state.

```
DCS = Completeness × Validation Pass Rate × Master Resolution Rate
```

| Dimension | Weight | Source |
|-----------|--------|--------|
| Completeness | 33% | Required fields populated / total required |
| Validation | 33% | Valid rows / total rows read |
| Resolution | 33% | Resolved rows / total canonical rows |

Score range: 0.0 → 1.0 (displayed as 0% → 100%)

A DCS below 95% triggers a steward review recommendation.

---

## 9.3 Event-Driven Intelligence Updates

Intelligence objects should be refreshed when underlying data changes.

```
New Batch Ingested
        ↓
Domain Event: BatchCompleted
        ↓
Intelligence Engine
        ↓
CompanyCommercialContext Updated
        ↓
Dashboard Refreshed
```

Phase 2 implementation — requires backend event bus.

---

## 9.4 Implementation Status

| Object | Status |
|--------|--------|
| Data Confidence Score calculation | **This sprint** (`batch_reporter.py`) |
| CompanyCommercialContext assembly | Phase 2 |
| CustomerAccountContext | Phase 2 |
| InventoryIntelligence | Phase 2 |
| FinancialPosition | Phase 2 |

---

## Engineering Decisions

- Commercial intelligence objects are the primary frontend consumption model
- The Data Confidence Score makes pipeline health visible to business users
- Intelligence updates are event-driven (Phase 2)
- No screen should assemble commercial context from multiple raw API calls

## Implementation Requirements

1. Implement Data Confidence Score calculation (`batch_reporter.py`)
2. Design CompanyCommercialContext schema (backend team — Phase 2)
3. Build intelligence assembly services (Phase 2)
4. Expose intelligence through Business APIs (Phase 2)

## Acceptance Criteria

- Every batch produces a Data Confidence Score
- Score is visible in pipeline output and batch report
- Score below 95% generates a steward review flag

## Developer Checklist

- [ ] `batch_reporter.py` with Data Confidence Score
- [ ] DCS displayed in `assimilate.py` batch summary
- [ ] CompanyCommercialContext schema (Phase 2)
- [ ] Intelligence services (Phase 2)

---

# Chapter 10

# Operational Readiness & Continuous Operations

## Engineering ACE as a Living Commercial Platform

---

## Purpose

Deployment marks the beginning, not the completion, of the platform's lifecycle.

Following go-live, ACE must continuously maintain trusted commercial context through operational monitoring, controlled change management, data governance, and pipeline observability.

---

## 10.1 Production Readiness Checklist

### Data Readiness

- [ ] All Sage 50 entities extracted successfully
- [ ] Bronze archives complete for all companies
- [ ] Quality validation: ≥99% completeness on required fields
- [ ] Master Data populated and aliases resolved
- [ ] Exception log reviewed and cleared
- [ ] Data Confidence Score ≥ 95%

### Pipeline Readiness

- [ ] All 5 pipeline stages operational
- [ ] Idempotent execution confirmed (run twice, same result)
- [ ] Exception log accessible and queryable
- [ ] Batch reporter operational
- [ ] Dry-run mode functional

### Backend Readiness

- [ ] All entities present in Synbot DB
- [ ] Business services operational
- [ ] API endpoints returning canonical data
- [ ] Authentication and authorization verified

### Operational Readiness

- [ ] `batch_reporter.py` operational for health checks
- [ ] Exception review process defined
- [ ] Data steward identified for each entity domain
- [ ] Ingestion schedule established

---

## 10.2 Batch Health Reporting

**File:** `batch_reporter.py`

The batch reporter provides post-ingestion operational visibility.

Usage:
```bash
python batch_reporter.py              # last batch
python batch_reporter.py --batch ID  # specific batch
python batch_reporter.py --all       # all batches summary
```

Outputs:
- Per-entity row counts (read → valid → canonical → resolved → uploaded)
- Exception counts by severity
- Data Confidence Score
- Status: HEALTHY / REVIEW_REQUIRED / FAILED

---

## 10.3 Continuous Improvement Cycle

```
Observe (batch_reporter.py)
        ↓
Measure (Data Confidence Score)
        ↓
Analyze (review exceptions.jsonl)
        ↓
Fix (correct source data in Sage 50)
        ↓
Re-run pipeline
        ↓
Observe
```

Every cycle improves data quality.

Every cycle strengthens commercial confidence.

---

## 10.4 Operational Monitoring

The operations team should monitor:

| Layer | Metric | Tool |
|-------|--------|------|
| Pipeline | Batch success rate | `batch_reporter.py` |
| Quality | Data Confidence Score | `batch_reporter.py` |
| Exceptions | Exception count by severity | `exceptions.jsonl` |
| Master Data | Unresolved references | `exceptions.jsonl` |
| Backend | API availability | Synbot health endpoint |

---

## 10.5 Trusted Commercial Context

The ultimate goal of every pipeline run is to establish **Trusted Commercial Context** — a governed, explainable representation of ACE's commercial reality that is complete enough to support business decisions.

Every engineering decision in this guide exists to strengthen that context:

```
Sage 50 Data
        ↓
Bronze (preserve)
        ↓
Quality (validate)
        ↓
Canonical (standardise)
        ↓
Master Resolution (unify)
        ↓
Silver (operationalise)
        ↓
Commercial Intelligence (understand)
        ↓
Trusted Commercial Context
        ↓
Business Decision
        ↓
Commercial Action
```

---

## Engineering Decisions

- Production operations are treated as an ongoing commercial capability
- Data quality monitoring runs after every batch
- Exceptions are reviewed on a defined cadence (weekly minimum)
- All pipeline changes go through engineering review before production
- The Data Confidence Score is the primary operational health indicator

## Implementation Requirements

1. `batch_reporter.py` — operational after this sprint
2. Exception review process documented and assigned
3. Ingestion schedule defined (daily / weekly)
4. DCS threshold: 95% minimum before production use
5. Backup/recovery procedure for Bronze archives

## Acceptance Criteria

- Platform can be deployed with validated operational readiness
- Monitoring provides visibility into pipeline health after every run
- Data Confidence Score is calculated and displayed for every batch
- Exception log is accessible and reviewed on defined cadence
- Continuous improvement is embedded in operational practice

## Developer Checklist

- [ ] `batch_reporter.py` implemented
- [ ] DCS displayed in `assimilate.py` output
- [ ] Exception review cadence defined
- [ ] Ingestion schedule established
- [ ] Production readiness checklist reviewed with operations team

---

# Appendix A — Domain Translation Table

| NL Synbot Health | ACE / Placeware | Notes |
|-----------------|-----------------|-------|
| DRM Hope HMS | Sage 50 | Source system |
| Patient | Customer | Primary commercial entity |
| Encounter | Transaction / Invoice | Commercial event |
| Clinical Activities | Business Operations | Buy, sell, stock |
| Drug Formulary | Product Catalog | Items master |
| Laboratory Orders | Purchase Orders | Procurement |
| Prescriptions | Sales Orders | Distribution |
| Billing | GL Entries | Financial records |
| Staff | Employees | Phase 3 |
| Departments | Business Units | planigli, plaphaen |
| Insurance | Credit Terms | Payment schedules |
| MRN | Customer Account No | Unique customer ID |
| Encounter ID | Invoice Number | Commercial event ID |
| Patient Clinical Context | Company Commercial Context | Dashboard object |
| Enterprise Trust Score | Data Confidence Score | Pipeline health |
| Workflow Engine | Transaction Lifecycle Engine | Phase 2 |
| Knowledge Engine | Commercial Intelligence Engine | Phase 2 |
| FHIR/HL7 | REST API / Excel | Future connectors |
| Diagnosis Catalog | Product Formulary | Item master |
| Insurance Plan | Payment Terms Master | Credit governance |

---

# Appendix B — ACE Framework Map

| NL Framework | ACE Equivalent | Status |
|-------------|---------------|--------|
| SIF (Synbot Integration Framework) | ACE Integration Layer | Implemented |
| SMEF (Master Data Engine) | ACE Master Data (Product, Customer, Vendor, COA) | Partial |
| SDF (Domain Framework) | Synbot commercial entities | Backend team |
| SWF (Workflow Framework) | Transaction Lifecycle Engine | Phase 2 |
| EKE (Knowledge Engine) | Commercial Intelligence Engine | Phase 2 |
| EXF (Experience Framework) | SynbotUI View Models | Frontend team |
| SAF (AI Framework) | Future AI analytics | Phase 3 |
| SOF (Observability Framework) | `batch_reporter.py` + Synbot monitoring | This sprint (batch level) |

---

# Appendix C — ACE Pipeline Quick Reference

```bash
# Full ingestion pipeline (both companies)
python assimilate.py

# Dry run (no DB writes, shows all 5 stages)
python assimilate.py --dry-run

# CSV ingestion (manual Sage exports)
python assimilate_from_csv.py

# Batch health report (last batch)
python batch_reporter.py

# Batch health report (all batches)
python batch_reporter.py --all

# View exceptions
type exceptions.jsonl
```

**Pipeline stage summary:**

| Stage | File | Input | Output |
|-------|------|-------|--------|
| 1 — Bronze | `bronze_layer.py` | Raw rows | JSON archive |
| 2 — Quality | `quality_engine.py` | Raw rows | Valid rows + QualityResults |
| 3 — Canonical | `canonical_mapper.py` | Valid rows | Canonical dicts |
| 4 — Master | `master_resolver.py` | Canonical dicts | Resolved dicts + ResolutionResults |
| 5 — Silver | `assimilate.py` (upload) | Resolved dicts | Synbot DB rows |
