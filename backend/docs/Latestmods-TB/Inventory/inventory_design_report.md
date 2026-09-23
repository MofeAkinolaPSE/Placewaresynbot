# Inventory Design Report

## Executive summary

The repository contains two inventory designs:

1. **Legacy/general inventory**: SKU-level event logging and stock summaries.
2. **Current pharmacy inventory workspace**: formulary-level catalogues, batch/lot stock, expiry, dispensing history, demand velocity, rule-based risk tiers, replenishment, and reporting.

The pharmacy workspace is the stronger design to reuse. It treats a drug as one UI card while retaining multiple batch rows underneath it, and it separates:

- **Position**: what is currently on the shelf and what it is worth.
- **Movement**: receipts, adjustments, dispensing, and recent activity.
- **Prediction**: demand-derived coverage, stockout date, risk tier, and reorder quantity.
- **Workflow**: replenishment requests and expiry disposal.

There is no clear tenant/client partition in the inventory tables or queries. “Per client” is currently implemented as **per drug/formulary item**, not per hospital/customer account.

## 1. Main data model

### Current pharmacy model

The active design is based on these tables:

- `royan_drug_formulary`: one catalogue row per drug, vaccine, consumable, or other item.
  - Identity: code, generic name, brand, form, strength, unit.
  - Planning overrides: `lead_time_days`, `safety_stock_days`, `reorder_level`.
  - Category: `drug`, `vaccine`, `consumable`, `other`.
- `royan_inventory_batches`: one row per received lot/batch.
  - `batch_number`, `quantity_on_hand`, `quantity_received`, `unit_cost`.
  - `supplier`, `location`, `received_at`, `expiry_date`.
  - External ETL identifiers and audit metadata.
  - Non-negative quantity/cost checks and a unique `(formulary_id, lower(batch_number))`.
- `royan_dispensing`: dispensing history, optionally linked to formulary and batch.
- `royan_prescriptions`: demand signal source.
- `royan_replenishment_requests`: recommendation-to-receipt workflow.
- `royan_pharmacy_item_rates`: separate historical price/margin source with MRP, purchase/cost/sale prices, batch, expiry, and stock.

The legacy `royan_drug_inventory` table is explicitly superseded. It has a one-row-per-drug shape and cannot represent concurrent lots with different expiry dates.

### Legacy/general model

The older `/inventory` routes use:

- `inventory_items`
- `stock_levels`
- `inventory_movements`
- `inventory_requests`
- `inventory_events`

The event route is append-only and supports `SALE`, `RESTOCK`, `DAMAGE`, `EXPIRY`, and `ADJUSTMENT`. Stock is calculated as baseline plus event delta, but the current implementation uses a zero baseline rather than loading an actual baseline quantity. This path should not be treated as the authoritative pharmacy design.

## 2. Stock lifecycle

### Receiving

`POST /pharmacy/inventory/drugs` creates an idempotent formulary drug and can optionally receive its first batch.

`POST /pharmacy/inventory/drugs/{formulary_id}/receive` receives stock. Re-receiving the same batch number tops up the existing row rather than creating a duplicate.

The UI uses catalogue typeahead before receiving, preventing duplicate drug rows when a user restocks an existing drug.

### Live stock and FEFO

“Live” stock means:

- `quantity_on_hand > 0`
- expiry is null or today/future

Live batches are sorted FEFO-style: earliest expiry first, then earliest receipt. Expired batches remain in the database for history but are excluded from dispensing pickers.

Dispensing applies a best-effort FEFO deduction. It floors at zero and does not block the clinical dispensing action if inventory bookkeeping is incomplete. The caller can compare requested quantity with quantities actually deducted to detect a shortfall.

### Adjustments and disposal

Batch adjustments change a specific batch quantity and retain a reason.

Expired stock is not deleted. Disposal sets quantity to zero and records what was destroyed, preserving a regulated audit trail. Partial disposal is supported.

## 3. API surfaces

### Current pharmacy workspace

- `GET /pharmacy/inventory/summary`
- `GET /pharmacy/inventory/cards`
- `GET /pharmacy/inventory/drugs`
- `GET /pharmacy/inventory/drugs/{formulary_id}`
- `GET /pharmacy/inventory/drugs/{formulary_id}/rates`
- `POST /pharmacy/inventory/drugs`
- `POST /pharmacy/inventory/drugs/{formulary_id}/receive`
- `POST /pharmacy/inventory/batches/{batch_id}/adjust`
- `GET /pharmacy/inventory/trends/most-prescribed`
- `GET /pharmacy/inventory/trends/recently-dispensed`
- `GET /pharmacy/inventory/expired`
- `POST /pharmacy/inventory/batches/{batch_id}/dispose`
- `GET /pharmacy/inventory/report`
- `GET /pharmacy/inventory/restock-suggestion/{formulary_id}`
- `POST /pharmacy/replenishment-request`
- `GET /pharmacy/replenishment-requests`
- `PATCH /pharmacy/replenishment-requests/{id}/status`

### Legacy/general inventory

- `POST /inventory/event`
- `GET /inventory/sku/{sku}`
- `GET /inventory/summary`
- Additional item, stock-level, movement, and request routes exist under `/inventory/*`.

## 4. Metrics and display cards

### Workspace KPI cards

The pharmacy page displays six top-level cards:

1. **Total SKUs**: number of drug cards with live stock.
2. **Stock Value**: sum of `quantity_on_hand * unit_cost`.
3. **Critical**: count of cards with `CRITICAL` risk.
4. **Warning**: count of cards with `WARNING` risk.
5. **Expiring Soon**: distinct drugs with stock expiring within the configured 30-day window.
6. **Pending Reorders**: replenishment requests in `recommended`, `approved`, or `ordered`.

The legacy dashboard separately displays:

- Total active SKUs.
- Low-stock count.
- Out-of-stock count.
- Critical item table with baseline, net event change, current stock, and status.
- Recent movement feed.

### Drug inventory card

One card represents one formulary drug, regardless of how many batches are on hand. It contains:

- Drug name, brand/category/form/strength.
- Total quantity on hand.
- Batch count.
- Nearest expiry and days remaining.
- Stock value.
- Risk tier badge.
- Stock coverage days.
- Recommended reorder quantity.
- Predicted stockout date.
- Demand confidence (`estimated` or `no_recent_demand`).
- Demand direction (`rising`, `falling`, `stable`).
- Reorder action for critical/warning items.

Cards can be filtered by category, risk tier, and search text. They are sorted by risk severity first, then drug name.

### Drill-down panel

The drill-down keeps live batches prominent and moves zero-stock/expired batches into history. It also shows recent dispensing, demand metrics, risk calculation, total stock, and a restock suggestion.

### Report tab

The report is intentionally a **position report**, not a movement report. It shows:

- Total stock value, in-stock batches, and drugs.
- Expiry exposure: expired, within 30 days, within 90 days, beyond 90 days, and no-date value.
- Batches without expiry dates.
- Dead stock: in-stock drugs never dispensed in their full history.
- Top drugs by stock value, quantity, batches, and whether ever dispensed.

The report comments record an observed state of approximately **₦50.7m on hand**, **618,452 migrated dispensing records**, and only **two dispensing events in the last 90 days**. These figures explain why recent movement alone would make the pharmacy appear empty.

## 5. Predictive and decision-support behavior

This is heuristic prediction, not machine learning.

### Demand velocity

Demand is calculated from `royan_prescriptions` over a configurable 30-day window, excluding imported placeholder rows:

- `avg_daily_demand = current_window_quantity / window_days`
- Current window is compared with the preceding equal window.
- Direction is:
  - `rising` if change is greater than 15%.
  - `falling` if change is less than -15%.
  - `stable` otherwise.
- No current/prior activity produces an explicit `no_recent_demand` confidence state rather than a fabricated estimate.

The service batches demand aggregation into one query for the catalogue. This replaced two queries per drug and addressed an observed approximately 18-second scan across roughly 536 drugs.

### Risk tiers

Defaults are environment-configurable:

- Lead time: 14 days.
- Safety stock: 7 days.
- Review cycle: 14 days.
- Expiring-soon window: 30 days.

For positive demand:

- `coverage_days = quantity_on_hand / avg_daily_demand`
- `CRITICAL` when coverage is below lead time.
- `WARNING` when coverage is below lead time plus safety stock.
- `MONITOR` when coverage is below lead time plus safety stock plus review cycle.
- `ADEQUATE` otherwise.

Special cases:

- Zero stock is `CRITICAL`.
- No demand is `CRITICAL` when stock is at/below `reorder_level`; otherwise `MONITOR`.
- Expiry within the configured window floors the result to at least `WARNING`.

### Reorder recommendation

With demand:

`recommended_qty = max(0, round(avg_daily_demand * (lead_time + safety_stock) - quantity_on_hand))`

Without demand:

`recommended_qty = max(0, round(reorder_level * 2 - quantity_on_hand))`

The predicted stockout date is today plus coverage days when demand is available.

### Restock suggestion

The restock endpoint uses the most recent historical batch to prefill supplier, location, unit cost, quantity context, and other receiving fields. If a prior received/expiry interval exists, it projects a new expiry by applying the observed shelf life to today; it never copies a past expiry date.

## 6. Replenishment workflow

1. A card reaches `CRITICAL` or `WARNING`, or a user opens reorder.
2. The UI pre-fills the calculated recommended quantity.
3. A request is created with status `recommended`.
4. It can move through `approved` → `ordered` → `received`, or `cancelled`.
5. The request stores formulary ID, requested quantity, ward, urgency (`routine`, `urgent`, `stat`), unit, notes, creator, and risk tier at request time.

There are also trigger/agent hooks for low stock and expiring stock. The low-stock trigger maps to replenishment creation; the expiry trigger maps to expiry/promotion handling. These hooks should be reviewed before reuse because older automation code references legacy table names in places.

## 7. Client/UI behavior

The primary implementation is [Inventory.tsx](C:/Users/DELL/Desktop/Moe/RoyanSynbot/SynbotUI/client/pages/Inventory.tsx). It has tabs for:

- Stock
- Trending
- Replenishment
- Expired Stock
- Report

Data is fetched with React Query, with the summary refreshing every 60 seconds. Stock changes invalidate cached dashboard data through an inventory realtime channel. Write controls are restricted in the UI to pharmacist/admin roles, while backend endpoints enforce role checks independently.

The older [InventoryDashboard.tsx](C:/Users/DELL/Desktop/Moe/RoyanSynbot/SynbotUI/client/components/dashboards/InventoryDashboard.tsx) is a separate general-inventory dashboard and should not be confused with the pharmacy workspace.

## 8. Data quality and design caveats

1. **No client/tenant isolation**: inventory queries have no `client_id`, hospital ID, or tenant scope. Porting to a multi-client product requires adding that key to formulary, batches, dispensing, requests, and every query/index.
2. **Legacy and current tables coexist**: use the pharmacy tables as the source of truth for pharmacy stock; do not mix them with `inventory_items` event totals.
3. **Expiry completeness is imperfect**: the opening migration created 536 synthetic `HOPE-INITIAL` batches. Only exact single-batch matches could safely recover real expiry dates; multi-batch rows were deliberately left without invented dates.
4. **Movement history is not suitable for current demand without migration awareness**: imported historical records are excluded from prescription velocity and recent-window metrics.
5. **Inventory does not hard-block dispensing**: this preserves clinical workflow but allows stock and dispensing to diverge; reconciliation/shortfall reporting is important in another implementation.
6. **Dead stock uses lifetime history**: this is deliberate because a recent-window definition would misclassify migrated stock as dead.
7. **Report query limits**: the report reads up to 5,000 in-stock batches; larger deployments should aggregate in SQL or paginate.
8. **Pricing is split**: stock valuation uses batch `unit_cost`; margin visibility uses `royan_pharmacy_item_rates`.
9. **Some automation is transitional**: inspect table names and workflow registration before copying low-stock automation.

## 9. Portable design blueprint

For another project, reproduce the current pharmacy design in this order:

1. Create a tenant/client-scoped formulary.
2. Store stock at batch/lot level, never only at product level.
3. Keep dispensing and movement history append-only.
4. Implement live-stock filtering and FEFO ordering.
5. Aggregate batch rows into one product card for the UI.
6. Compute demand velocity from a clearly defined, migration-aware source.
7. Use explicit no-data states instead of false forecasts.
8. Add configurable lead time, safety stock, review cycle, reorder floor, and expiry window.
9. Derive risk, coverage, stockout date, and reorder quantity from those inputs.
10. Separate stock position, movement trends, expiry/dead-stock reporting, and replenishment workflow.
11. Preserve disposal/audit history instead of deleting expired stock.
12. Add client/tenant scoping and SQL aggregation before scaling beyond a single hospital.

## Source files reviewed

- [pharmacy_inventory_service.py](C:/Users/DELL/Desktop/Moe/RoyanSynbot/backend/src/services/pharmacy_inventory_service.py)
- [pharmacy_inventory.py](C:/Users/DELL/Desktop/Moe/RoyanSynbot/backend/src/routers/pharmacy_inventory.py)
- [inventory.py](C:/Users/DELL/Desktop/Moe/RoyanSynbot/backend/src/services/inventory.py)
- [inventory_module.py](C:/Users/DELL/Desktop/Moe/RoyanSynbot/backend/src/routers/inventory_module.py)
- [Inventory.tsx](C:/Users/DELL/Desktop/Moe/RoyanSynbot/SynbotUI/client/pages/Inventory.tsx)
- [DrugInventoryCard.tsx](C:/Users/DELL/Desktop/Moe/RoyanSynbot/SynbotUI/client/components/pharmacy/DrugInventoryCard.tsx)
- [InventoryReportTab.tsx](C:/Users/DELL/Desktop/Moe/RoyanSynbot/SynbotUI/client/components/pharmacy/InventoryReportTab.tsx)
- [InventoryDashboard.tsx](C:/Users/DELL/Desktop/Moe/RoyanSynbot/SynbotUI/client/components/dashboards/InventoryDashboard.tsx)
- [174_pharmacy_inventory_batches.sql](C:/Users/DELL/Desktop/Moe/RoyanSynbot/backend/migrations/174_pharmacy_inventory_batches.sql)
- [216_real_batches_and_expiry.sql](C:/Users/DELL/Desktop/Moe/RoyanSynbot/backend/migrations/216_real_batches_and_expiry.sql)
- [195_pharmacy_item_rates_schema.sql](C:/Users/DELL/Desktop/Moe/RoyanSynbot/backend/migrations/195_pharmacy_item_rates_schema.sql)
- [constants.py](C:/Users/DELL/Desktop/Moe/RoyanSynbot/backend/src/constants.py)
