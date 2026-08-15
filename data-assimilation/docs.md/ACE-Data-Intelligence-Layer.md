# ACE Data Intelligence Layer

**Version:** 1.0

**Platform:** ACE / Placeware Nigeria Limited

**Prepared By:** Placeware Data Engineering

**Delivers:** `ACE-Implementation-Guide.md` Chapter 9 ("Commercial Intelligence Layer") Phase 2 — `CustomerAccountContext` / `InventoryIntelligence`.

---

# Chapter 1 — Purpose & Scope

## 1.1 Origin

`backend/docs/Latestmods-TB/Nl-Data-mod/Data Engine/` (RoyanHealth's data-engineering doc set) proposes a "Synbot Data Intelligence Layer (SDIL)" — a Data Lineage Engine, a Relationship Auditor, a Patient Context Engine, and a Clinical Data Explorer, described entirely in hospital terms (Patient/MRN/Doctor/Lab/Encounter).

This document translates that proposal into ACE's commercial domain. It does **not** re-translate `NL-Application-blueprint.md` / `NL-implement-guide1.md` — that work already exists as `ACE-Data-Blueprint.md` / `ACE-Implementation-Guide.md` and is partially executed (`bronze_layer.py → quality_engine.py → canonical_mapper.py → master_resolver.py`).

Separately, `Data Engine/plan1.md` (a "we have 183 tables and no data-engineering structure" conversation) turned out, on inspection, to almost certainly be about **this app itself** — Placeware's migrations define 173–182 `CREATE TABLE` statements, suspiciously close to "183." Migration `086_silver_layer_views.sql` already acted on it (11 dead tables archived, Bronze→Silver views added), but the concrete follow-on engineering plan attached to a copy of that file (`data-assimilation/docs.md/data-engineer.md`) was written for a different, sibling codebase ("RoyanSynbot" — `royan_patients`, MySQL "Hope" source) and was never re-targeted at ACE. This layer is that re-targeting, scoped to the diagnostic/visibility pieces only.

## 1.2 In scope

- **Data Lineage Engine** → Field Coverage Matrix (Chapter 2)
- **Relationship Auditor** → Relationship/Orphan Auditor + Table Classification (Chapter 3)
- **Clinical Data Explorer** → Commercial Data Explorer (Chapter 4)
- **Patient Context Engine** → already substantially covered by `crm_360.py`'s Customer 360 for customers; the Commercial Data Explorer generalizes it for vendors/items (Chapter 4 §4.5)

## 1.3 Explicitly out of scope (future phases)

DB-backed DLQ/watermarks/circuit breakers, Pydantic entity contracts, a Gold star-schema (Fact/Dim tables), RBAC views, a pipeline orchestrator v2 — the sibling `data-engineer.md` RoyanSynbot plan's structural patterns are reusable inspiration for these, but none of its code (or `royan_*` naming) was ported. Not built in this phase.

## 1.4 Appendix A extension — Domain Translation Reference

Extends `ACE-Data-Blueprint.md`'s existing table:

| Synbot Health (NL Data Engine) | ACE / Placeware |
| --- | --- |
| Hope column (source) | Sage column candidate (DAT) / CSV header (live import) |
| Synbot column (target) | ACE canonical column |
| Mapping Registry | `backend/src/data_intel/entity_field_maps.py` |
| Coverage Calculator | `lineage_service.field_coverage_report()` |
| Relationship Scanner (FK metadata) | `relationship_auditor_service.scan_information_schema()` |
| Orphan Detector | `relationship_auditor_service.scan_soft_relationships()` |
| Integrity Score | `relationship_auditor_service.integrity_score()` |
| Patient Context Engine | `crm_360.py` (customers, unchanged) + `explorer_service.get_record()` (vendors/items) |
| Clinical Data Explorer | Commercial Data Explorer (`data_explorer.py` + `DataIntelligence.tsx`) |
| MRN / Patient search | Customer/vendor code, SKU, invoice #, GL account code search |
| Developer Mode (trace to source) | `developer_trace` field on `GET /explorer/record/{type}/{key}` |
| Data Quality Indicators (🟢/🟡/🔴) | `quality_badge` (green/amber/red), computed from `REQUIRED_FIELDS` + orphan status |

### Engineering Decisions

- Build as `backend/` FastAPI services, not `data-assimilation/` CLI scripts — the backend is the only continuously-running, live-DB-connected process (confirmed via `backend/Dockerfile`: `data-assimilation/` is never copied into `chat-backend.v1`).
- Add a third, explicitly-labelled mirror of the Sage field mappings (`entity_field_maps.py`) rather than a fourth ad-hoc registry — the two-registry problem (`field_maps.py` vs `sage_csv_import.py`'s `_map_*` functions) is a documented finding, not silently patched.

### Implementation Requirements

- New package `backend/src/data_intel/` (pure data: `entity_field_maps.py`, `soft_relationships.py`).
- New services `backend/src/services/{lineage_service,relationship_auditor_service,explorer_service}.py`.
- New routers `backend/src/routers/{data_intelligence,data_explorer}.py`, registered in `app.py`.

### Acceptance Criteria

- No changes to `data-assimilation/` or `sage_csv_import.py` — this layer is purely additive/read-only.
- `crm_360.py` untouched.

### Developer Checklist

- [ ] `backend/src/data_intel/__init__.py` package created
- [ ] `entity_field_maps.py` mirrors `field_maps.ENTITY_MAPS` + CSV-native entities
- [ ] `soft_relationships.py` registry created with the `SOLD_%` special case

---

# Chapter 2 — Data Lineage Engine (Field Coverage Matrix)

## 2.1 The two-registry finding

This app has two independently maintained Sage-field-mapping registries: `data-assimilation/field_maps.py` (`ENTITY_MAPS`, historical DAT migration only) and `backend/src/routers/sage_csv_import.py`'s `_map_*` functions (live `POST /sage/import/csv` path). There is no single source of truth between them. This is reported as a finding, not silently fixed — see Chapter 1's "Future Phases."

## 2.2 Coverage matrix format

Per entity, per ACE column: `Sage Column (candidates) | ACE Column | Coverage %`, computed live against the latest import batch of the relevant Silver view or snapshot table. DAT-translated entities and CSV-native entities (near-1:1 passthrough: `gl_detail`, `cash_register`, `gl_account_summary`, `customer_sales`) are reported in **separate sections** — blending them would misleadingly pad the coverage numbers.

## 2.3 Non-extractable fields (written record)

`STXHDR`/`STXROW` (never entered), `JRNLHDR`/`INVCOST` (non-LSTRING binary), `UNITMEAS`/`TAXCODE`/`COST`/`BUDGET`/`BANKREC` (non-LSTRING), `EMPLOYEE`/`PROJECT` (empty), `CONTACTS.DAT`/`ADDRESS.DAT` (non-standard UUID-prefixed format, not yet extracted). `ExpiryDate`/`LotCode` successfully extracted into `sage_items_snapshot`. `JRNLROW.DAT` GL entries extracted via Btrieve LVAR streaming into `sage_gl_transactions` — amounts not extractable. See `lineage_service.NON_EXTRACTABLE_FIELDS`.

### Engineering Decisions

- Coverage is computed against the **latest batch only** (mirrors the Silver-view convention from migrations 086/087) — historical batches would understate current data quality.
- "Sage Column" shown is the candidate list, not a confirmed single winner — true per-row column provenance isn't persisted anywhere today. Future phase: `canonical_mapper.transform()` writing a `resolved_columns` sidecar.

### Implementation Requirements

- `lineage_service.field_coverage_report()`, `missing_columns_report()`, `NON_EXTRACTABLE_FIELDS`.
- Cached 5 minutes (`src/cache.ttl_cache`) — a diagnostic report, staleness is acceptable.

### Acceptance Criteria

- DAT-translated and CSV-native sections render separately.
- Non-extractable-fields narrative present and accurate.
- `missing_columns_report()` priority-sorts required fields first.

### Developer Checklist

- [ ] `GET /data-intel/coverage` returns both sections + narrative
- [ ] Spot-check 2-3 columns manually against `psql` counts

---

# Chapter 3 — Relationship Auditor & Table Classification

## 3.1 Soft-relationship registry

Most linkage in this schema is untyped text columns (`customer_id`, `sku`, `account_code`), not DB-enforced FKs — `scan_information_schema()` is expected to return few rows; that's the schema's actual state, reported as-is. The real relationship graph lives in `soft_relationships.RELATIONSHIPS`, bootstrapped from joins already exercised in code.

**The `SOLD_%` gotcha**: `sage_invoice_lines_snapshot.invoice_id` is overloaded — real invoice lines carry a real invoice number, but `crm_360.py` also writes a synthetic `SOLD_<customer_code>` pseudo-invoice-id for "top purchased items." Modelled as two separate edges (`ar_invoice_lines_to_invoice` excludes `SOLD_%`; `sold_items_to_customer` matches only `SOLD_%`, stripped) so the synthetic convention never corrupts the real edge's orphan count.

## 3.2 Integrity Score

Row-count-weighted average across edges — **not** `batch_reporter.py`'s multiplicative Data Confidence Score. DCS multiplies *sequential* pipeline-stage pass rates over the same base (correct there — each stage filters the prior stage's output). Relationship edges are *parallel/independent* measurements; multiplying N of them would unfairly crush the score toward zero purely because more edges were added. Same status vocabulary as `batch_reporter.py` (`HEALTHY` ≥95%, `REVIEW_REQUIRED` ≥50%, `FAILED` <50%).

## 3.3 Table classification methodology

Live `information_schema.tables` scan (not a static migrations-file grep, which over/undercounts due to `IF NOT EXISTS` redeclarations), cross-referenced against text search of `backend/src/routers`, `backend/src/services`, and `backend/migrations`. **Core** = referenced from Python. **Referenced** = SQL-only (e.g. behind a Silver view). **Unused** = zero references found anywhere. Already-archived tables (migration 086's 11) live in the `_archive` schema and are reported separately, never re-flagged.

**Never auto-archives.** This tool surfaces candidates; a human reviews and writes the migration, exactly like the 11 tables already archived.

### Engineering Decisions

- Table classification is mechanically derived (a coarser 3-way split than a human curator would make) by design — it surfaces candidates, it does not decide.
- Cached 10 minutes (`classify_tables()` walks the filesystem — expensive relative to a request, cheap relative to how often the schema actually changes).

### Implementation Requirements

- `relationship_auditor_service.{scan_information_schema, scan_soft_relationships, sample_orphans, integrity_score, classify_tables}`.
- `child_where_clause()` is public (not underscore-prefixed) specifically so `explorer_service.py` reuses the exact same batch/filter SQL assembly — one place, not two.

### Acceptance Criteria

- `sold_items_to_customer` edge shows near-100% coverage, not false orphans.
- Already-archived 11 tables show as "Already Archived," not re-flagged as Unused.
- `classify_tables()` / `scan_soft_relationships()` never issue a write.

### Developer Checklist

- [ ] `GET /data-intel/relationships` — edges + real FKs
- [ ] `GET /data-intel/relationships/{name}/orphans` — sample rows
- [ ] `GET /data-intel/integrity-score` — weighted, not compounding
- [ ] `GET /data-intel/tables` — classification + already-archived list

---

# Chapter 4 — Commercial Data Explorer

## 4.1 Search & drill-down

Unified search across `v_customers`, `v_vendors`, `v_inventory`, `v_chart_of_accounts`, `v_ar_invoices` (code/name/phone/invoice #). Drill-down (`get_record`) assembles: `canonical` (Silver row), `bronze_history` (last 20 imports by key — native Postgres, no filesystem dependency), `related` (soft-relationship edge counts, reused from Chapter 3), `quality_badge` (🟢/🟡/🔴, computed from `REQUIRED_FIELDS` + orphan status — a real rule), `developer_trace` (ACE column → Sage candidates → live coverage % → value history).

## 4.2 Filesystem-boundary caveat

`original_source_record` (trace to the literal Bronze JSON archive from the historical DAT migration) and `exceptions` (cross-reference to `exceptions.jsonl`) are **omitted in this phase** — confirmed via `backend/Dockerfile` that the backend container has no filesystem access to `data-assimilation/`. Both fields are present in the API response, set to `null`, with a documented future upgrade path (an optional `pipeline_exceptions` table + best-effort dual-write from `exception_manager.log()`).

## 4.3 Not a graph visualizer

`related` renders as a simple list, not an interactive graph/tree component — ACE's commercial schema is 2-3 levels deep (customer → invoice → line), not RoyanHealth's 5-8-level clinical graph. Revisit if the schema grows deeper.

## 4.4 Not cached

Unlike Chapter 2/3's diagnostic endpoints, `/explorer/search` and `/explorer/record/*` are live on every request — this is an active-investigation tool, staleness mid-lookup would be misleading.

## 4.5 Context Engine decision

`crm_360.py`'s `customer_360` stays exactly as-is (working, shipped, embedded as a modal in `CRM.tsx`) — not touched, not cloned. `explorer_service.get_record()` is the generalized context engine going forward, closing the gap for vendors and items specifically (customers already have a dedicated view).

### Engineering Decisions

- Five master entity types only (customers, vendors, items, GL accounts, invoices) — not every snapshot table is independently searchable.
- Quality badge logic lives in `explorer_service._quality_badge()`, using its own `_VIEW_REQUIRED_FIELDS` — deliberately NOT `entity_field_maps.REQUIRED_FIELDS` (Chapter 2's coverage matrix queries raw snapshot tables, e.g. `item_id`/`net_amount`; the Explorer's `canonical` row comes from the Silver view, which renames those same columns, e.g. `sku`/`total_amount` — reusing the raw-table field list against a view row would flag every record as broken).

### Implementation Requirements

- `explorer_service.{search, get_record}`.
- `backend/src/routers/data_explorer.py`: `GET /explorer/search`, `GET /explorer/record/{entity_type}/{key}`.
- Frontend: `SynbotUI/client/pages/DataIntelligence.tsx` (Explorer tab), `api-client.ts` `dataIntel.{search,record}`.

### Acceptance Criteria

- `GET /explorer/record/customers/<known-good-code>` → 🟢, populated `bronze_history` and `developer_trace`.
- `GET /explorer/record/sage_ar_snapshot/<bad-customer_id-row>` → 🔴, orphan correctly detected.
- `original_source_record` / `exceptions` present as `null`, not omitted from the payload shape.

### Developer Checklist

- [ ] Search returns results across all 5 entity types
- [ ] Badge colors match `QualityControl.tsx` conventions (no new palette)
- [ ] `/admin/data-intelligence` gated to `admin` role (`ProtectedRoute.tsx` + backend `require_role("admin")`)

---

# Chapter 5 — Verification & Rollout

## 5.1 Phase A — backend only (docker cp, no rebuild)

| # | Check | Endpoint | Expected |
|---|---|---|---|
| 1 | Table count | `GET /data-intel/tables` | Already-archived 11 show "Already Archived"; total matches live `information_schema.tables` |
| 2 | `SOLD_%` special case | `GET /data-intel/relationships` | `sold_items_to_customer` near-100%, not false orphans |
| 3 | Coverage sections | `GET /data-intel/coverage` | DAT vs CSV-native separated; non-extractable narrative present |
| 4 | Score behavior | `GET /data-intel/integrity-score` | Weighted average, not compounding toward 0 |
| 5 | Good record | `GET /explorer/record/customers/<known-good-code>` | 🟢, populated history + trace |
| 6 | Bad record | `GET /explorer/record/sage_ar_snapshot/<bad-row>` | 🔴, orphan detected |

## 5.2 Phase B — frontend (`npm run build:client` + container restart)

- `/admin/data-intelligence` loads for `admin`, redirects otherwise
- All 4 tabs render against live data; search returns results across all 5 entity types
- Badge colors match `QualityControl.tsx`

## 5.3 Manual checklist

- [ ] Table classification results reviewed by a human before any new `_archive` migration is written
- [ ] Integrity score spot-checked by hand against one known relationship in `psql`
- [ ] Coverage % spot-checked against 2-3 columns manually

---

# Appendix B — Endpoint Reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/data-intel/tables` | Table classification (Core/Referenced/Unused/Already-Archived) |
| GET | `/data-intel/relationships` | Soft-relationship edges + real FKs |
| GET | `/data-intel/relationships/{name}/orphans` | Sample orphan rows for one edge |
| GET | `/data-intel/integrity-score` | Overall + per-edge weighted score |
| GET | `/data-intel/coverage` | Field coverage matrix + missing columns + non-extractable narrative |
| GET | `/explorer/search` | Unified search across 5 master entity types |
| GET | `/explorer/record/{entity_type}/{key}` | Full drill-down for one record |

All endpoints require `admin` role (`Depends(require_role("admin"))`).

---

# Appendix C — curl Quick Reference

```bash
TOKEN="<bearer token>"
BASE="http://localhost:8000"

curl -H "Authorization: Bearer $TOKEN" "$BASE/data-intel/tables"
curl -H "Authorization: Bearer $TOKEN" "$BASE/data-intel/relationships"
curl -H "Authorization: Bearer $TOKEN" "$BASE/data-intel/relationships/sold_items_to_customer/orphans?limit=10"
curl -H "Authorization: Bearer $TOKEN" "$BASE/data-intel/integrity-score"
curl -H "Authorization: Bearer $TOKEN" "$BASE/data-intel/coverage"
curl -H "Authorization: Bearer $TOKEN" "$BASE/explorer/search?q=acme"
curl -H "Authorization: Bearer $TOKEN" "$BASE/explorer/record/customers/<customer_code>"
```
