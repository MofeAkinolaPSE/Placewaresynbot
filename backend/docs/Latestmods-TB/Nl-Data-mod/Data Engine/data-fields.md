# DrM File — Complete Data Scan Report
**Scanned:** 2026-06-26  
**Files scanned:** 36 SQL files (compressed + uncompressed)  
**Unique tables found:** 533 | **Tables with data:** 364

---

## What's In The Dump Folder

| File | Size | Tables | Purpose |
|---|---|---|---|
| `data1712.sql` | 2,757 MB | 506 defined, 300 with data | Full Hope DB dump — 2017 |
| `db_drmnigeria-20230619.sql.gz` | 461 MB | 506 / 301 | Full Hope DB dump — 2023 |
| `db_drmnigeria-20240201.sql.gz` | 505 MB | 506 / 301 | Full Hope DB dump — 2024 |
| `db_drmnigeria-20260125.sql.gz` | 654 MB | 506 / 301 | Full Hope DB dump — 2026 (most recent) |
| `hope_master_nigeria-20230619.sql.gz` | 0.2 MB | 23 / 17 | Master catalog only — 2023 |
| `hope_master_nigeria-20240201.sql.gz` | 0.2 MB | 23 / 17 | Master catalog only — 2024 |
| `hope_master_nigeria-20260125.sql.gz` | 0.2 MB | 23 / 17 | Master catalog only — 2026 |
| `master_15feb21.sql` | 1.1 MB | 23 / 17 | Master catalog — 2021 |
| `RhosP/` | — | — | Full Hope CakePHP source code + older schema backups |

---

## HIGH-VALUE TABLES FOUND

### Group A — Fill Empty RoyanHealth Tables

These tables map directly to RoyanHealth tables that currently have 0 records.

#### 1. `wards` → `royan_wards`
**34 rows** in all data dumps

| Hope Column | RoyanHealth Column | Notes |
|---|---|---|
| `id` | `external_id` | |
| `name` | `name` | "First Floor", "Ground Floor", "Stepdown Unit", "NEONATAL", etc. |
| `ward_type` | `ward_type` | "Non-ICU", "ICU" |
| `no_of_rooms` | — | informational |
| `bed_cost` | — | maps to tariff |
| `is_active`, `is_deleted` | `is_active` | |

**Action:** Extract and seed `royan_wards` — 34 real ward names from the hospital.

---

#### 2. `beds` → `royan_beds`
**1,236 rows** in all data dumps

| Hope Column | RoyanHealth Column | Notes |
|---|---|---|
| `id` | `external_id` | |
| `room_id` | — | links to `rooms` table (91 rows) |
| `bedno` | `bed_number` | bed label e.g. "B-01" |
| `under_maintenance` | `status` | maintenance flag |
| `is_released` | `status` | occupied/available |
| `location_id` | — | which hospital branch |

**Action:** Extract → seed `royan_beds` with real bed numbers per ward. Also links to `rooms` (91 rows) for consulting room data.

---

#### 3. `consultants` + `doctors` → `royan_staff`
**6,969 + 609 = 7,578 rows** across dumps

| Hope Column | RoyanHealth Column | Notes |
|---|---|---|
| `id` | `external_id` | |
| `first_name` + `last_name` | `full_name` | |
| `designation_id` → `designations` | `designation` | 1,517 designations available |
| `speciality` | `designation` | e.g. "Medicine", "Surgery" |
| `email` | `email` | |
| `mobile_phone` / `phone` | `phone` | |
| `is_active` | `is_active` | |

**Action:** Extract → seed `royan_staff` with real doctor/consultant roster. This also fixes the **consulting_doctor** field on encounters — currently 0.0% populated because the staff table is empty.

---

#### 4. `insurance_companies` → `royan_hmos`
**36,858 rows** (this is cumulative across all dumps; unique companies much less)

| Hope Column | RoyanHealth Column | Notes |
|---|---|---|
| `id` | `external_id` | |
| `name` | `name` | "NHIS", "AXA Mansard", "Hygeia", etc. from Nigeria dump |
| `phone` | `contact_phone` | |
| `email` | `contact_email` | |
| `insurance_type_id` | — | links to `insurance_types` (87 rows) |
| `Status` | `is_active` | |

**Action:** Extract Nigeria-specific HMOs from `db_drmnigeria-20260125.sql.gz` → seed `royan_hmos`. This unblocks the entire HMO billing workflow.

---

#### 5. `tariff_lists` → `royan_service_catalog`
**13,722 rows** (cumulative; unique services ~1,000–2,000)

| Hope Column | RoyanHealth Column | Notes |
|---|---|---|
| `id` | `external_id` | |
| `name` | `name` | Service name |
| `service_type` | `category` | consultation/lab/pharmacy/ward/procedure |
| `price_for_private` | `base_price` | Private rate |
| `service_category_id` → `service_categories` (269 rows) | `category` | |
| `is_deleted` | `is_active` | |

**Action:** Extract → seed `royan_service_catalog`. This enables `billing_bucket` routing to be accurate (real service categories instead of heuristic guessing).

---

#### 6. `pharmacy_items` → Drug Formulary Reference
**44,674 rows**

| Hope Column | Notes |
|---|---|
| `MED_NAME` | Drug name (e.g. "Amoxicillin 500mg") |
| `name` | Full drug description |
| `MED_STRENGTH` | Strength (e.g. "500mg") |
| `MED_STRENGTH_UOM` | Unit (mg, ml, etc.) |
| `MED_ROUTE_ABBR` | Route (oral, IV, IM) |
| `rxcui` | RxNorm code (international standard) |
| `code` | Hospital formulary code |

**Action:** Extract → create drug formulary reference table or load into `royan_service_catalog` (pharmacy category). Enables autocomplete in pharmacy UI and validates drug_name against formulary.

---

### Group B — Backfill Existing Data

These tables can update records that already exist in RoyanHealth but have empty fields.

#### 7. `ward_patients` (33,486 rows) → Fix `royan_encounters.ward_id + bed_id`

**Critical.** This table links patient → ward → bed with admission/discharge dates.

| Hope Column | Maps To |
|---|---|
| `patient_id` | resolve to `royan_patients.id` via external_id |
| `ward_id` | `royan_encounters.ward_id` |
| `bed_id` | `royan_encounters.bed_id` |
| `in_date` | `royan_encounters.triage_at` (approximate) |
| `out_date` | `royan_encounters.discharge_at` |
| `is_discharge` | `royan_encounters.status` = 'discharged' |

**Action:** After seeding `royan_wards` and `royan_beds`, parse `ward_patients` to backfill `ward_id` and `bed_id` on inpatient encounters. Currently 0.0% populated.

---

#### 8. `discharge_details` (27,995 rows) → Fix `royan_encounters.discharge_at`

| Hope Column | Maps To |
|---|---|
| `patient_id` | resolve to `royan_patients.id` |
| `ward_id` + `bed_id` | cross-reference |
| `discharge_starts_on` | `royan_encounters.discharge_at` |
| `discharge_ends_on` | complement |

**Action:** Backfill `discharge_at` on encounters — currently 0.0% (only 17 PESE test records).

---

#### 9. `guardians` (41,585 rows) → Fix Patient NOK Data

| Hope Column | Maps To |
|---|---|
| `person_id` | resolve to `royan_patients.id` (via persons table) |
| `guar_first_name` + `guar_last_name` | `royan_patients.next_of_kin_name` |
| `guar_phone` / `guar_mobile` | `royan_patients.next_of_kin_phone` |
| `guar_relation` | (no RoyanHealth column — informational) |

**Note:** Sample data shows many NULL guardians — fill rate may be low. Run scan first.  
**Action:** Backfill `next_of_kin_name` and `next_of_kin_phone` on `royan_patients`.

---

#### 10. `bmi_bp_results` (563,433 rows) + `bmi_results` (563,432 rows) → `royan_vitals`

| Hope Column | Maps To |
|---|---|
| `systolic` | `royan_vitals.bp_systolic` |
| `diastolic` | `royan_vitals.bp_diastolic` |
| `pulse_text1` | `royan_vitals.pulse` |
| `bmi_result_id` → `bmi_results` | |

`bmi_results` likely has: `weight`, `height`, `bmi`, `temperature` — need schema confirmation.

**Action:** Extract and load into `royan_vitals`. With 563K rows this is a major dataset. Currently `royan_vitals` has only 17 records.

---

### Group C — New Clinical Data Not Yet Imported

These are complete clinical datasets that have no corresponding populated table in RoyanHealth yet.

#### 11. `radiology_test_orders` (155,768 rows) + `radiology_reports` (145,509 rows)

Hope has a full radiology module with orders AND results.

| Hope Table | Hope Column | Notes |
|---|---|---|
| `radiology_test_orders` | `patient_id`, `radiology_id` (→ `radiologies` catalog), `doctor_id`, `start_date`, `status` | Radiology orders |
| `radiology_reports` | `radiology_order_id`, `report`, `resulted_by`, `resulted_at` | Reports/results |
| `radiologies` (1,783 rows) | `name` | Radiology test catalog (X-ray, MRI, CT, etc.) |

**Action:** These need new tables in RoyanHealth: `royan_radiology_orders` and `royan_radiology_results`. This is 155K clinical records currently not in the system at all.

---

#### 12. `icds` (34,500 rows) → `royan_icd10_codes`

Full ICD-10 code reference table already exists in Hope. `royan_icd10_codes` table is defined in RoyanHealth but has 0 records.

| Hope Column | Maps To |
|---|---|
| `code` | `royan_icd10_codes.code` |
| `name` / `description` | `royan_icd10_codes.description` |
| `category` | `royan_icd10_codes.category` |

**Action:** Bulk-load → `royan_icd10_codes`. Enables ICD-10 autocomplete in the encounter diagnosis form.

---

#### 13. `notes` (683,064 rows) → `royan_encounter_notes`

Hope's `notes` table contains clinical notes per encounter.

| Hope Column | Maps To |
|---|---|
| `patient_id` | `royan_encounter_notes.patient_id` |
| `note_text` / content columns | `royan_encounter_notes.content` |
| `note_type` | `royan_encounter_notes.note_type` |
| `created_by` | `royan_encounter_notes.author_name` |
| `create_time` | `royan_encounter_notes.created_at` |

**Action:** Extract and load → `royan_encounter_notes`. Currently 19 records (all test data).

---

## Summary: Extraction Priority Matrix

| Priority | Table(s) | Records | Fills What | Complexity |
|---|---|---|---|---|
| P0 — NOW | `wards`, `beds` | 34 + 1,236 | `royan_wards`, `royan_beds` — unblocks ward tracking | Low |
| P0 — NOW | `consultants` + `doctors` | ~7,578 | `royan_staff` — fixes consulting_doctor 0% | Low |
| P1 | `insurance_companies` | ~1,000 unique | `royan_hmos` — unblocks HMO billing | Medium |
| P1 | `tariff_lists` | ~2,000 unique | `royan_service_catalog` — fixes billing routing | Medium |
| P1 | `ward_patients` | 33,486 | Backfill `ward_id`/`bed_id` on encounters | Medium |
| P1 | `discharge_details` | 27,995 | Backfill `discharge_at` on encounters | Medium |
| P2 | `icds` | 34,500 | `royan_icd10_codes` — enables ICD-10 UI | Low |
| P2 | `guardians` | 41,585 | Backfill patient NOK fields | Medium |
| P2 | `pharmacy_items` | 44,674 | Drug formulary reference | Medium |
| P3 | `bmi_bp_results` / `bmi_results` | 563K | `royan_vitals` — massive vital signs dataset | High |
| P3 | `radiology_test_orders` + `radiology_reports` | 155K + 145K | New `royan_radiology_*` tables | High |
| P3 | `notes` | 683K | `royan_encounter_notes` — clinical notes | High |

---

## What Cannot Be Extracted

| Data | Why |
|---|---|
| Patient blood group / genotype | Not stored in Hope's `patients`/`persons` table (confirmed: 0% in our audit) |
| Patient allergies | `patient_allergies` has only 75 rows — mostly demo data |
| Medication administration records (MAR) | Only 436 rows — sparse; Hope doesn't enforce this workflow |
| Consent records | Not in Hope |
| Nursing care plans | Not in Hope |

---

## Additional Source Files Found (RhosP Folder)

The `RhosP/` folder contains the full **Hope CakePHP source code** — useful for understanding exact field names and business logic but not for data extraction. Key files:

- `app/Config/Schema/db_Hope.sql` — Hope DB schema (schema only, no data)
- `app/Controller/` — 80+ PHP controllers (Consultants, Pharmacy, Laboratory, Billing, etc.)
- `app/Vendor/hope_data*.sql` — Additional master data files (hope_data.sql, hope_data_21_march.sql, etc.)

The vendor SQL files have: `departments` (3,089 rows), `insurance_companies` (36,858 rows), `corporates` (248 rows), `tariff_lists` (13,722 rows).
