We need to implement data engineering techniques to this application, we currently have 183 tables and I think it's too much.
I believe the problem could be that we haven't implemented any core data engineering concepts to help manage our pipelines. Kindly perform a study, since you know our application. What techniques could we had to our app that would assist managing the DB 
"
Data engineer database management techniques encompass the architectural strategies, pipeline integrations, and system optimizations used to store, secure, and retrieve large volumes of data. These core techniques ensure databases remain scalable, performant, and reliable for analytics and application operations.1. Data Modeling & ArchitectureSchema Design: Choosing between Star Schema or Snowflake Schema for data warehouses to optimize read speeds and reduce data redundancy.Partitioning: Breaking large tables into smaller, manageable chunks based on ranges, lists, or hash keys (e.g., partitioning sales data by year) to limit the amount of data scanned during queries.Indexing: Utilizing B-tree, Bitmap, or spatial indexes on frequently filtered columns to dramatically accelerate data retrieval, balancing this against write latency.2. Scalability & DistributionSharding: Distributing horizontal partitions of data across multiple database servers (nodes) to balance read/write loads and scale capacity linearly.Horizontal vs. Vertical Scaling: Preferring horizontal scaling (adding more database instances) over vertical scaling (upgrading RAM/CPU on a single machine) to prevent single points of failure.Distributed Computing Integration: Managing connection pools and data flow from frameworks like Apache Spark or Apache Flink to distributed database engines.3. Performance Tuning & Query OptimizationQuery Profiling: Analyzing query execution plans to identify bottlenecks, such as slow nested-loop joins or full table scans, and rewriting them using more efficient operations.Caching: Deploying in-memory layers like Redis or utilizing materialized views for frequently aggregated reports, preventing the database from recomputing data constantly.Vacuuming & Compaction: Running routine maintenance operations in databases like PostgreSQL or data lakes (e.g., Apache Iceberg/Delta Lake compaction) to reclaim storage and clean up obsolete data.4. Reliability & GovernanceReplication & High Availability: Implementing master-slave or multi-master replication to guarantee fault tolerance and ensure database uptime even during hardware failures.Backup & Recovery: Establishing automated, point-in-time recovery (PITR) procedures and regular snapshots to prevent data loss in disaster scenarios.Access Control & Security: Enforcing strict Role-Based Access Control (RBAC), data masking, and column-level encryption to maintain compliance with data privacy regulations." For example the short study above


---

# 1. Root Diagnosis (Why you have 183 tables)

From what I know about your system:

* Queue-first design (Patients → Tickets → Services)
* Multiple operational workflows (audit, deviation, maintenance, etc.)
* Likely heavy use of **Zoho Creator / low-code forms → auto tables**

What likely happened:

* Each module = new table (instead of extending core entities)
* No **canonical data model (CDM)** (single source of truth)
* No separation between:

  * **Operational data (OLTP)** → app usage
  * **Analytical data (OLAP)** → reporting

👉 Result:

* Redundant tables
* Poor query performance
* Hard-to-maintain pipelines
* No clear data flow

---

# 2. What You Actually Need (Core Data Engineering Layers)

Instead of “more techniques,” you need **structure + layering**.

### A. Medallion Architecture (Critical Upgrade)

This is the missing backbone.

```
Raw Layer (Bronze)  →  Clean Layer (Silver)  →  Business Layer (Gold)
```

**How it applies to your system:**

* **Bronze (Raw ingestion)**

  * Zoho tables / MySQL tables (183 tables live here)
  * No transformation
  * Append-only logs

* **Silver (Normalized core model)**

  * Cleaned + deduplicated
  * Unified entities:

    * Patients
    * Queue Tickets
    * Services
    * Staff
    * Transactions

* **Gold (Business views)**

  * Reports:

    * Daily queue load
    * Service turnaround time
    * Audit compliance rates

👉 This alone will reduce logical complexity by ~60–70%.

---

# 3. Fix the Biggest Issue: Data Modeling (You need a Core Schema)

Right now, you likely have:

> “One table per process”

You need:

> “Few core entities + extensible attributes”

---

## Recommended Core Model (SynBot Health)

Instead of 183 tables, compress into ~25–40 structured ones:

### Core Entities

* Patients
* Visits / Encounters
* Queue_Tickets
* Services
* Staff
* Locations

### Operational Extensions

* Audit_Logs
* Deviations
* Maintenance_Records
* Fumigation (from your doc)
* Recall_Events

👉 Notice: these are **linked**, not isolated.

---

## Apply Star Schema for Analytics

For reporting layer:

### Fact Tables

* Fact_Queue
* Fact_Service_Usage
* Fact_Audit

### Dimension Tables

* Dim_Patient
* Dim_Service
* Dim_Time
* Dim_Staff

👉 This removes heavy joins across 100+ tables during analytics.

---

# 4. Table Reduction Strategy (Practical Move)

Don’t delete tables blindly. Do this:

### Step 1 — Table Classification

Group your 183 tables into:

* Core (must keep)
* Redundant (duplicates)
* Log tables
* Temporary / unused

---

### Step 2 — Merge Pattern

If you have tables like:

* `fumigation_records`
* `maintenance_records`
* `audit_records`

👉 Merge into:

```
operations_events
- id
- type (fumigation | audit | maintenance)
- date
- status
- metadata (JSON)
```

This is called:
👉 **Polymorphic Event Modeling**

---

### Step 3 — Introduce JSON Columns (Controlled Flexibility)

Instead of new tables:

```
service_config
- id
- name
- config_json
```

Use JSON for:

* Dynamic attributes
* Form-driven fields

---

# 5. Pipeline Engineering (You’re Missing This Layer)

Right now, your DB = system of record only.

You need pipelines:

### ETL / ELT (Extract, Transform, Load)

**Stack (low-code first):**

* Zoho Flow / n8n → ingestion
* MySQL → storage
* dbt (data build tool) → transformation
* Metabase / Superset → analytics

---

### Example Flow

```
Zoho Tables → (ETL) → MySQL Raw
            → (dbt) → Clean Tables
            → (Views) → Dashboard
```

---

# 6. Performance Techniques You SHOULD Implement

### 1. Partitioning (High Impact)

Apply to:

* Queue_Tickets (by date)
* Audit logs (by month)

👉 Reduces query scan massively

---

### 2. Indexing (Critical)

Add indexes on:

* patient_id
* service_id
* status
* created_at

---

### 3. Materialized Views (Game changer for dashboards)

Instead of:

* Calculating queue stats every time

Store:

```
daily_queue_summary
```

---

### 4. Caching Layer

Use:

* Redis

For:

* Active queue state
* Real-time dashboards

---

# 7. Reliability & Governance (You’re partially doing this already)

From your uploaded docs:

* Audit systems
* Deviations tracking
* Maintenance schedules

👉 That’s governance—but not system-level.

---

## What to Add:

### A. Data Lineage

Track:

* Where data comes from
* How it transforms

Tool:

* dbt documentation

---

### B. RBAC (Role-Based Access Control)

* Admin
* Radiographer
* Auditor

Restrict:

* Table access
* Column visibility

---

### C. Backup Strategy (You mentioned this already)

Implement:

* Daily snapshots
* Point-in-time recovery (PITR)

---

# 8. The Real Fix (Simple Roadmap)

### Phase 1 — Stabilize

* Classify 183 tables
* Identify duplicates
* Add indexes

---

### Phase 2 — Restructure

* Introduce core entities
* Merge redundant tables
* Add JSON-based extensibility

---

### Phase 3 — Pipeline Layer

* Introduce ETL (Zoho → MySQL)
* Add dbt transformations
* Build Silver + Gold layers

---

### Phase 4 — Optimize

* Partition tables
* Add caching (Redis)
* Create materialized views

---

# Final Reality Check

Your issue is not “too many tables.”

It’s:

> ❌ No unified data architecture
> ❌ No pipeline layer
> ❌ No separation of concerns

Fix those, and:

* 183 tables becomes manageable
* Query performance improves
* System becomes scalable

---
Use the information above, understand the concepts and lets apply them to this project. 
Lets lean up our data base and have Primary and foriegn keys. set up when needed. I think our schema is to complication which is why we are having issues with the assimilation and display, lets clean up the table and a 




Ready for review
Select text to add comments on the plan
RoyanSynbot Data Assimilation — FAANG-Grade Medallion Architecture Upgrade
Context
The DRM Hope MySQL source has 183 tables with no separation of concerns — every module spawned its own table, no canonical data model, no pipeline layering. The current data-assimilation/ pipeline does a flat Extract → SQLite Stage → Transform → PostgreSQL Load. This gets data in but has no data quality gates, silent row drops, no incremental sync, no analytics layer, and two stub transformers (radiology, theatre) that do nothing.

Goal: Implement a full Medallion Architecture (Bronze → Silver → Gold) over the existing well-structured 47-table PostgreSQL schema, add data contracts + DLQ, complete all transformers, build the analytics Gold layer, add RBAC views, compound indexes, and a production-grade orchestrator.

Architecture
SOURCE (MySQL dump / CSV — 183 Hope tables)
       │
       ▼
[BRONZE]  SQLite staging — run_id, content_hash, append-only
       │
       ▼
[SILVER]  PostgreSQL royan_* tables — Pydantic contracts, ON CONFLICT upserts, DLQ
       │
       ▼
[GOLD]    Fact/Dim tables, materialized views, royan_operations_events
       │
       ▼
[CACHE]   Redis — active queue counts per department (TTL 5 min)
Phase 1 — Bronze Layer Hardening
Goal: Audit-safe, replayable staging with run_id tracking and DLQ.

New Files
data-assimilation/staging/run_context.py — RunContext dataclass: run_id (uuid4), source, mode (full|incremental), started_at, dry_run
data-assimilation/migrations/116_bronze_watermarks_dlq.sql — Two new PostgreSQL tables:
-- Tracks max external_updated_at per entity for incremental mode
CREATE TABLE royan_ingest_watermarks (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity                  text NOT NULL UNIQUE,
    last_run_id             text NOT NULL,
    max_external_updated_at timestamptz,
    rows_processed          int NOT NULL DEFAULT 0,
    full_run_at             timestamptz,
    incremental_run_at      timestamptz,
    updated_at              timestamptz NOT NULL DEFAULT now()
);

-- Dead Letter Queue — rows that fail validation or load; NEVER silently dropped
CREATE TABLE royan_ingest_dlq (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          text NOT NULL,
    entity          text NOT NULL,
    external_id     text,
    source_table    text,
    raw_row         jsonb NOT NULL,
    failure_stage   text NOT NULL CHECK (failure_stage IN ('extract','contract','transform','load')),
    failure_reason  text NOT NULL,
    error_detail    jsonb,
    retry_count     int NOT NULL DEFAULT 0,
    resolved        boolean NOT NULL DEFAULT false,
    resolved_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);
-- Indexes: (entity, created_at DESC), (run_id), partial (entity, resolved) WHERE resolved=false
Modified Files
data-assimilation/staging/sqlite_store.py — Add run_id TEXT and content_hash TEXT columns to all entity tables; write() accepts run_id param; hash = sha256(json.dumps(row, sort_keys=True))[:16]
Phase 2 — Silver Layer: Contracts + Transformers
Goal: Every entity has a Pydantic v2 schema contract. All rejects go to DLQ. Complete all stub transformers.

New Files
data-assimilation/contracts/ package (new directory):

base.py — BaseContract(BaseModel) with model_config = {"str_strip_whitespace": True, "extra": "ignore"}, required external_source, external_id
patient_contract.py — validates gender enum, blood_group enum, required first_name/last_name
billing_contract.py — all six fee columns (consultation_fee, lab_charges, pharmacy_charges, ward_charges, procedure_charges, miscellaneous), with _route_amount() helper using source category / service_type column
appointment_contract.py, lab_contract.py, pharmacy_contract.py, admission_contract.py
radiology_contract.py — study_type, body_region, ordering_doctor, status, report_text, performed_at, reported_at
theatre_contract.py — procedure_name, surgeon, anaesthetist, status, theatre_room, started_at, ended_at, duration_mins, anaesthesia_type
operations_contract.py — event_type enum (audit|deviation|maintenance|fumigation|recall), event_date, title, status, severity, department, metadata: dict, source_table
hmo_contract.py, patient_insurance_contract.py
New transformers:

data-assimilation/transformers/radiology.py — Full implementation (was 9-line stub); uses RADIOLOGY_MAP
data-assimilation/transformers/theatre.py — Full implementation (was 9-line stub); uses THEATRE_MAP
data-assimilation/transformers/operations.py — Polymorphic transformer; classifies rows by source_table name into event_type; output goes to royan_operations_events
data-assimilation/transformers/hmo.py — HMO + patient_insurance transformer; uses existing HMO_MAP
Modified Files
data-assimilation/transformers/field_maps.py — Add:

RADIOLOGY_MAP: maps radiology_id/xray_id/imaging_id → external_id; study_type/modality; body_part/region; requesting_doctor; report/findings
THEATRE_MAP: maps theatre_id/operation_id → external_id; procedure_name; surgeon; anaesthetist; theatre_room; started_at/ended_at
OPERATIONS_MAP: generic operational fields (date, status, notes, performed_by, department)
HMO_PLAN_MAP, PATIENT_INSURANCE_MAP
Extend TABLE_HINTS:
"radiology":         ["radiology_orders", "xray_orders", "imaging_orders", "tbl_radiology"],
"theatre":           ["theatre_records", "surgical_records", "operations", "theatre_cases"],
"operations":        ["fumigation_records", "maintenance_records", "deviations", "audit_records"],
"hmo_plans":         ["hmo_plans", "insurance_plans", "tbl_hmo_plans"],
"patient_insurance": ["patient_insurance", "patient_hmo", "member_insurance"],
Fix BILLING_MAP: remove "total_amount": "miscellaneous" family; add "category": "category_hint" and "service_type": "category_hint" to enable fee routing in transformer
data-assimilation/transformers/billing.py — Priority bug fix: Add _route_amount(mapped, raw_row) that reads category_hint and routes to the correct fee column; output must include all six columns instead of dumping everything to miscellaneous

data-assimilation/ingest.py — Extend ENTITY_ORDER to include new entities; add deprecation notice

Phase 3 — Gold Layer: Analytics Schema
Goal: Star Schema fact/dim tables, materialized views, polymorphic operations events table.

New Files
data-assimilation/migrations/120_medallion_analytics.sql

-- Polymorphic Operations Events (merges 5+ Hope source tables into one)
CREATE TABLE royan_operations_events (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type      text NOT NULL CHECK (event_type IN ('audit','deviation','maintenance','fumigation','recall')),
    event_date      date NOT NULL,
    title           text NOT NULL,
    status          text NOT NULL DEFAULT 'open',
    severity        text CHECK (severity IN ('low','medium','high','critical')),
    performed_by    text,
    department      text,
    metadata        jsonb NOT NULL DEFAULT '{}',
    source_table    text,       -- data lineage: which Hope table this came from
    run_id          text,
    external_source text,
    external_id     text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (external_source, external_id)
);

-- Dimension Tables
CREATE TABLE dim_patient (patient_sk bigint PK, patient_id bigint FK, mrn, full_name, gender,
    age_band TEXT, -- '0-5','6-17','18-40','41-60','60+'
    hmo_provider, is_active, valid_from, valid_to);  -- SCD Type 2 ready

CREATE TABLE dim_service (service_sk bigint PK, service_id FK, service_code UNIQUE, service_name, category, base_price);
CREATE TABLE dim_staff   (staff_sk bigint PK, staff_id FK, staff_number UNIQUE, full_name, department, designation, employment_type);

CREATE TABLE dim_time (
    date_day date PRIMARY KEY,
    day_of_week int, day_name text, week_of_year int,
    month_num int, month_name text, quarter int, year int,
    is_weekend boolean, is_nigerian_holiday boolean DEFAULT false
);
-- Populated via generate_series('2020-01-01', '2030-12-31', '1 day')

-- Fact Tables (PARTITION BY RANGE on date column, partitions for 2024/2025/2026 + default)
CREATE TABLE fact_queue_visits (
    visit_date date NOT NULL, patient_sk FK, encounter_id FK,
    encounter_type, department, status, triage_level,
    wait_minutes numeric, consult_minutes numeric, total_visit_minutes numeric,
    consulting_doctor text, run_id text
) PARTITION BY RANGE (visit_date);

CREATE TABLE fact_billing_summary (
    billing_date date NOT NULL, patient_sk FK, billing_id FK,
    consultation_fee, lab_charges, pharmacy_charges, ward_charges,
    procedure_charges, miscellaneous, total_charged,
    hmo_covered, patient_balance, payment_method, status, run_id
) PARTITION BY RANGE (billing_date);

-- Materialized Views (REFRESH CONCURRENTLY after each Gold load)
CREATE MATERIALIZED VIEW mv_daily_queue_stats AS
    SELECT created_at::date AS visit_date, department,
        COUNT(*) AS total_visits,
        COUNT(*) FILTER (WHERE status='discharged') AS completed,
        AVG(EXTRACT(EPOCH FROM (triage_at - created_at))/60) AS avg_wait_mins,
        AVG(EXTRACT(EPOCH FROM (discharge_at - created_at))/60) AS avg_total_mins
    FROM royan_encounters GROUP BY 1,2;

CREATE MATERIALIZED VIEW mv_service_utilization AS
    SELECT category, service_code, description,
        COUNT(*) AS usage_count, SUM(gross_amount) AS total_revenue,
        AVG(gross_amount) AS avg_price
    FROM royan_bill_items GROUP BY 1,2,3;
data-assimilation/loaders/gold_loader.py — Functions:

refresh_dim_patient(conn) — upserts dim_patient from royan_patients; derives age_band from date_of_birth
refresh_dim_staff(conn), refresh_dim_service(conn)
populate_fact_queue_visits(conn, run_id, since=None) — inserts from royan_encounters; filters by since in incremental mode
populate_fact_billing_summary(conn, run_id, since=None) — inserts from royan_billing + royan_bill_items
refresh_materialized_views(conn) — REFRESH CONCURRENTLY both MVs
Phase 4 — Performance & Governance
Goal: Compound indexes, audit log partitioning, RBAC views.

New Files
data-assimilation/migrations/121_indexes_partitions.sql

-- Compound indexes on Silver tables
CREATE INDEX idx_royan_enc_patient_created     ON royan_encounters (patient_id, created_at DESC);
CREATE INDEX idx_royan_lab_patient_created     ON royan_lab_orders (patient_id, ordered_at DESC);
CREATE INDEX idx_royan_prescriptions_patient   ON royan_prescriptions (patient_id, prescribed_at DESC);
CREATE INDEX idx_royan_billing_patient_created ON royan_billing (patient_id, billed_at DESC);
CREATE INDEX idx_royan_enc_status_created      ON royan_encounters (status, created_at DESC);
CREATE INDEX idx_royan_appt_status_created     ON royan_appointments (status, booked_at DESC);
-- Partial index for active encounters (dashboard hot path)
CREATE INDEX idx_royan_enc_active ON royan_encounters (department, status)
    WHERE status NOT IN ('discharged');
CREATE INDEX idx_royan_bill_items_service ON royan_bill_items (service_id, created_at DESC)
    WHERE service_id IS NOT NULL;

-- Audit log partitioning (creates partitioned clone; rename requires maintenance window)
CREATE TABLE royan_audit_logs_p (LIKE royan_audit_logs INCLUDING ALL)
    PARTITION BY RANGE (created_at);
-- Monthly partitions 2024–2026 + default
data-assimilation/migrations/122_rbac_views.sql

-- Nurse: demographics + encounter status; NO billing/HMO data
CREATE VIEW v_nurse_patients AS
    SELECT id, mrn, first_name, last_name, date_of_birth, gender,
           blood_group, genotype, allergies, phone, is_active, registered_at
    FROM royan_patients WHERE is_active = true;

-- Radiographer: radiology worklist from operations_events
CREATE VIEW v_radiographer_worklist AS
    SELECT id AS event_id, event_date, title AS study_description, status,
           performed_by AS radiographer,
           metadata->>'study_type' AS study_type,
           metadata->>'ordering_doctor' AS ordering_doctor, created_at
    FROM royan_operations_events WHERE department IN ('Radiology');

-- Auditor: full audit log + operations events; patient PII columns excluded
CREATE VIEW v_auditor_audit_log AS
    SELECT id, event_type, event_class, action, outcome, reason_code,
           actor_id, actor_role, subject_type, subject_id, trace_id,
           approval_reason, details, created_at
    FROM royan_audit_logs;
Modified Files
data-assimilation/loaders/db_loader.py — Add:

load_operations_events(conn, rows, dry_run) — upserts to royan_operations_events
load_to_dlq(conn, run_id, entity, failures) — bulk inserts rejected rows to royan_ingest_dlq
update_watermark(conn, entity, run_id, max_updated_at, rows_processed) — upsert to royan_ingest_watermarks
get_watermark(conn, entity) -> Optional[str] — returns max_external_updated_at for incremental filter
Phase 5 — Pipeline Orchestrator v2
Goal: Production-grade pipeline.py with parallel processing, circuit breakers, incremental mode, structured logging.

New Files
data-assimilation/pipeline.py — Replaces ingest.py as primary entry point:

Sequential entities (FK order): patients → hmo → appointments → admissions → patient_insurance
Parallel entities (ThreadPoolExecutor, max_workers=4): lab, pharmacy, billing, radiology, theatre, operations
Key components:

EntityCircuitBreaker — CLOSED → OPEN after max_failures=3 consecutive failures; skips entity for rest of run; other entities unaffected
_apply_watermark_filter(rows, watermark) — keeps only rows where external_updated_at > watermark (rows without updated_at pass through)
_validate_and_split(entity, rows, contract_class) — returns (valid_rows, dlq_failures); Pydantic ValidationError → DLQ, never dropped
Structured logging via structlog: each entity emits {run_id, entity, rows_seen, rows_upserted, rows_dlq, duration_s, error_rate} at INFO level; pipeline emits pipeline.complete summary
data-assimilation/pipeline_config.py — PipelineConfig dataclass:

max_workers: int = 4
circuit_breaker_threshold: int = 3
incremental_lookback_hours: int = 2   # overlap window for late-arriving rows
dlq_batch_size: int = 100
gold_refresh_enabled: bool = True
redis_url: Optional[str] = None
log_format: str = "console"           # "json" | "console"
data-assimilation/cache/redis_client.py — Optional; only active when REDIS_URL is set:

class QueueCache:
    # Warms Redis after each run
    # Key: royan:queue:{department}:active_count  TTL: 300s
    def warm_active_queue(self, conn, redis_client) -> None: ...
    def invalidate_entity(self, redis_client, entity: str) -> None: ...
Modified Files
data-assimilation/config.py — Add REDIS_URL, PIPELINE_MAX_WORKERS, PIPELINE_MODE, LOG_FORMAT
data-assimilation/requirements.txt — Add pydantic>=2.0,<3.0, structlog>=23.0, redis>=5.0, pyarrow>=14.0
data-assimilation/.env.example — Add REDIS_URL, PIPELINE_MAX_WORKERS, PIPELINE_MODE, LOG_FORMAT
data-assimilation/ingest.py — Add deprecation notice at top; keep intact for --step discover
Complete File Inventory
New Files (23)
Path	Purpose
pipeline.py	v2 orchestrator — parallel, circuit breakers, incremental, structured logs
pipeline_config.py	PipelineConfig dataclass
staging/run_context.py	RunContext (run_id, mode, timestamps)
contracts/__init__.py	Package init
contracts/base.py	BaseContract (Pydantic v2)
contracts/patient_contract.py	Patient validation
contracts/billing_contract.py	Billing + fee-routing contracts
contracts/appointment_contract.py	Appointment validation
contracts/lab_contract.py	Lab order validation
contracts/pharmacy_contract.py	Prescription validation
contracts/admission_contract.py	Admission/encounter validation
contracts/radiology_contract.py	Radiology study contract
contracts/theatre_contract.py	Surgical event contract
contracts/operations_contract.py	Polymorphic ops event contract
contracts/hmo_contract.py + patient_insurance_contract.py	HMO contracts
transformers/operations.py	Polymorphic ops transformer
transformers/hmo.py	HMO/insurance transformer
loaders/gold_loader.py	Gold layer dim/fact population + MV refresh
cache/redis_client.py	Redis queue cache warmer
migrations/116_bronze_watermarks_dlq.sql	DLQ + watermarks tables
migrations/120_medallion_analytics.sql	Gold schema (ops_events, dims, facts, MVs)
migrations/121_indexes_partitions.sql	Compound indexes + audit log partitioning
migrations/122_rbac_views.sql	Nurse / radiographer / auditor views
Modified Files (9)
Path	Key Changes
staging/sqlite_store.py	Add run_id + content_hash per row
transformers/field_maps.py	RADIOLOGY_MAP, THEATRE_MAP, OPERATIONS_MAP, TABLE_HINTS extension, BILLING_MAP fix
transformers/billing.py	Critical bug fix: route amounts to correct fee columns
transformers/radiology.py	Full implementation (was stub)
transformers/theatre.py	Full implementation (was stub)
loaders/db_loader.py	load_operations_events, load_to_dlq, watermark CRUD
ingest.py	Deprecation notice + new entity dispatches
config.py	REDIS_URL, PIPELINE_MAX_WORKERS, PIPELINE_MODE, LOG_FORMAT
requirements.txt	pydantic>=2.0, structlog>=23.0, redis>=5.0, pyarrow>=14.0
Implementation Order (Sprint Sequence)
1. requirements.txt              — install deps (no code risk)
2. 116 migration                 — apply to DB
3. sqlite_store.py               — run_id/hash (backward compatible)
4. contracts/ package            — pure Python
5. field_maps.py + billing.py    — highest-priority bug fix
6. radiology.py + theatre.py     — complete stubs
7. operations.py + hmo.py        — new transformers
8. 120 migration                 — Gold schema
9. gold_loader.py
10. 121 + 122 migrations         — low-traffic window
11. db_loader.py additions
12. pipeline.py + supporting files
13. redis_client.py              — optional, gated by REDIS_URL
Key Design Decisions
Decision	Rationale
Pydantic v2 not v1	Rust-backed, 10x faster; extra="ignore" cleanly absorbs unknown Hope columns
content_hash in Bronze	Enables diff on re-export — unchanged rows skip re-transformation
ThreadPoolExecutor over asyncio	psycopg2 is synchronous; asyncpg refactor is out of scope
royan_operations_events in Gold	Derived merge of 5+ Hope tables; lineage preserved via source_table column
RBAC via views, not RLS	Lower-risk first step; doesn't require backend session changes; RLS can layer on later
No partitioning on patients/encounters	Tables small enough; compound indexes sufficient; audit_logs is the right partition target
Verification
Schema: Apply migrations 116 → 120 → 121 → 122 in order; \dt in psql confirms all new tables/views exist.
Dry run: python pipeline.py --source csv --folder ./test_fixtures --mode full --dry-run — verify structured JSON log with run_id, all entity entries, pipeline.complete summary.
Billing fix: Insert a Hope billing row with category=lab; verify lab_charges > 0 and miscellaneous == 0.
DLQ: Submit a patient row with empty patient_id; verify row appears in royan_ingest_dlq with failure_stage=contract and resolved=false.
Incremental: Seed watermark at time T; submit 100 rows where 30 have updated_at > T; verify exactly 30 rows processed.
Gold: After Silver load, run gold_loader.populate_fact_queue_visits(); verify rows land in correct partition (e.g., fact_queue_visits_2025).
RBAC: SELECT * FROM v_nurse_patients must not include hmo_id, hmo_provider, or billing columns.
Circuit breaker: Mock a loader that always raises; verify after 3 failures the entity is skipped and other entities complete normally.