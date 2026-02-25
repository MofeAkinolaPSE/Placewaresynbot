Here’s a **clean execution prompt** you can give your backend agent.

It’s structured to enforce enterprise discipline without premature overengineering.

---

# Backend Agent Prompt

## Objective: Implement Enterprise-Grade Data Pipeline (Scalable, Modular, Deterministic)

You are implementing the core data pipeline for SynBot.

This must follow enterprise (Meta-level) architecture principles while remaining lean for current scale.

The system must be:

* Deterministic
* Idempotent
* Auditable
* Configurable
* Industry-agnostic
* Horizontally scalable in the future

Do not overengineer infrastructure prematurely. Build clean foundations.

---

# 1️⃣ Architectural Structure (Mandatory)

Implement a layered pipeline with strict separation of concerns:

### Layer 1 — Ingestion Layer

Responsibilities:

* Accept external data (APIs, uploads, database pulls)
* Timestamp and tag all records
* Assign ingestion_id
* Persist raw payload unchanged

Rules:

* Raw data must never be mutated
* Store raw records separately
* All ingestion must be idempotent

---

### Layer 2 — Validation Layer

Responsibilities:

* Schema validation
* Required field checks
* Type validation
* Reject malformed records
* Log validation errors

Rules:

* Use strict schema contracts
* No business logic here
* Validation must not transform data

---

### Layer 3 — Normalization Layer

Responsibilities:

* Map raw data → internal domain models
* Standardize field names
* Normalize timestamps
* Resolve enumerations via config

Rules:

* All mappings must be config-driven
* No industry hardcoding
* Output must conform to typed domain entities

---

### Layer 4 — Feature Computation Layer

Responsibilities:

* Compute KPIs
* Aggregate metrics
* Derive calculated fields

Rules:

* KPI formulas must not live inside agents
* KPI definitions must be registered modules
* Feature computation must be deterministic
* No side effects

---

### Layer 5 — Intelligence Layer

Responsibilities:

* Risk scoring
* Insight generation
* Trigger evaluation
* Workflow state updates

Rules:

* Risk scoring must use configurable weights
* No hardcoded thresholds
* All rules must defer to config
* All decisions must be logged

---

### Layer 6 — API / Consumption Layer

Responsibilities:

* Serve structured insights
* Provide audit logs
* Expose processed features
* Support dashboard queries

Rules:

* No business logic here
* Read-only access to processed layers
* Query optimization via indexing

---

# 2️⃣ Non-Negotiable Engineering Requirements

## Determinism

Given the same input → output must always be identical.

## Idempotency

Reprocessing the same ingestion_id must not duplicate or corrupt data.

## Observability

Each stage must:

* Log execution time
* Log error counts
* Log transformation stats

## Auditability

For any insight produced, we must trace back:

* Raw record
* Normalized entity
* Feature set
* Risk calculation
* Trigger rules applied

Implement lineage tracking.

---

# 3️⃣ Storage Strategy (Lean but Scalable)

Implement logical separation:

* raw_data_table
* validated_data_table
* normalized_entities_table
* computed_features_table
* insights_table
* audit_log_table

Design schema to scale horizontally later.

Do not introduce distributed systems unless throughput requires it.

---

# 4️⃣ Config-Driven System (Critical)

All domain-specific behavior must be configurable:

* Status mappings
* KPI formulas
* Risk weights
* Threshold triggers
* Workflow state definitions

Core pipeline must not reference industry-specific terminology.

---

# 5️⃣ Performance & Scaling Strategy (Future-Proofing)

Design with:

* Batch processing capability
* Async job execution support
* Event-driven compatibility
* Stateless processing units

Ensure easy migration path to:

* Message queues
* Stream processors
* Distributed workers

But do not implement them unless required.

---

# 6️⃣ Code Quality Standards

* Strong typing for domain models
* Clear interface contracts between layers
* Unit tests for each layer
* Integration test for full pipeline
* No logic duplication across layers
* Explicit error handling
* Clean dependency injection

---

# 7️⃣ What Not To Do

Do NOT:

* Embed KPI formulas inside agents
* Hardcode workflow states
* Mix ingestion with transformation logic
* Use global mutable state
* Store transformed data without raw reference
* Skip audit logging

---

# 8️⃣ Final Deliverables

Provide:

1. Pipeline architecture diagram (logical)
2. Folder structure
3. Domain model definitions
4. Example config structure
5. Sample end-to-end data flow example
6. Test strategy
7. Scalability roadmap (v2 evolution)

---

The goal is to build a clean, enterprise-grade pipeline foundation that:

* Supports multi-industry configuration
* Maintains executive-grade reliability
* Scales without redesign
* Preserves strict governance

Implement with discipline. Not complexity.

---

If you'd like, I can also create:

* A stricter “Principal Engineer version”
* Or a lighter “MVP execution version”

Just tell me the stage you’re optimizing for.
