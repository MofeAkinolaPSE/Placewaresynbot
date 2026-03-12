
#	File	Rows	Notes
1	inventory.csv	~80	Vaccine & pharma SKUs, NGN unit costs, batch IDs, expiry dates (mix of near-expiry + healthy stock)
2	ar.csv	~200	Hospital/pharmacy invoices — mix of Open, Partial, Paid; some overdue 30/60/90 days
3	ap.csv	~130	Vendor bills from J&J, Pfizer, GSK, MSD, LogiCold — some overdue
4	gl.csv	~120	Monthly P&L lines Jan 2025–Dec 2025; Revenue, COGS, OPEX accounts
5	customers.csv	~40	Nigerian hospitals, clinics, pharmacies — with customer codes, contacts, tiers
6	staff.csv	~35	Full staff: Finance, Sales, Ops, HR, Management depts — with emails, roles
P0 — Operational Seed SQL (applied as a migration or seeder script)
#	File	Tables seeded	Notes
7	backend/data/seed_storage_zones.sql	placeware_storage_zones	Cold Room A/B, Freezer 1, Ambient — capacities, current load, temp ranges
8	backend/data/seed_temperature_logs.sql	placeware_temperature_logs	30 days of hourly sensor readings per zone — 2 violation events included
9	backend/data/seed_staff.sql	placeware_staff	Mirror of staff.csv with user UUIDs for RLS linkage
10	backend/data/seed_riders.sql	riders	8 delivery riders — names, vehicles, active status
11	backend/data/seed_inventory_items.sql	inventory_items, stock_levels	Canonical SKU catalogue + per-zone stock quantities
P1 — Procurement & Import Clearance
#	File	Tables seeded	Notes
12	backend/data/seed_suppliers.sql	suppliers, supplier_deliveries	6 vendors — Pfizer, J&J, GSK, MSD, LogiCold, AstraZeneca
13	backend/data/seed_shipments.sql	placeware_shipments, placeware_procurement_shipments, placeware_procurement_shipment_events	4 active shipments in various clearance stages; 1 with a delay alert
14	backend/data/seed_batch_locks.sql	batch_status_locks	2 batches locked pending NAFDAC release
15	backend/data/seed_replenishments.sql	replenishment_requests	3 approved replenishment POs in flight
P1 — CRM & Commercial
#	File	Tables seeded	Notes
16	backend/data/seed_crm.sql	leads, customers, opportunities, crm_activities, crm_prospects	~15 customers, ~30 opportunities across pipeline stages, activity history
17	backend/data/seed_campaigns.sql	campaigns, placeware_kpi_leads_by_campaign, placeware_kpi_leads_by_source	3 campaigns — immunisation drive, hospital tender outreach, retail pharmacy push
18	backend/data/seed_orders.sql	placeware_orders, deliveries, routes, placeware_tracking	~25 orders — mix of fulfilled, in-transit, pending
P1 — Project Controls
#	File	Tables seeded	Notes
19	backend/data/seed_projects.sql	placeware_projects, placeware_scope_items, placeware_cost_items, placeware_risk_register, placeware_change_requests	3 projects: Cold Room Expansion, NAFDAC Re-certification, ERP Integration
P2 — Productivity & Intelligence Layer
#	File	Tables seeded	Notes
20	backend/data/seed_calendar.sql	placeware_calendar_events, placeware_tasks	NAFDAC inspection dates, delivery milestones, staff reviews, open tasks
21	backend/data/seed_alerts.sql	placeware_alerts	5–8 seeded alerts: low stock, overdue AR, temperature violation, clearance delay
22	backend/data/seed_support.sql	support_tickets, crm_followups	~10 open tickets, ~15 scheduled follow-ups
23	backend/data/seed_timesheets.sql	placeware_timesheets, hr_payroll_snapshot, hr_absence_snapshot	Last 4 weeks of timesheet data per staff
P3 — Derived / Agent-Computed (seeded as snapshots for demo, replaced by agents at runtime)
#	File	Tables seeded	Notes
24	backend/data/seed_kpis.sql	placeware_kpis, placeware_kpi_opportunities_by_stage	~20 KPI values: AR overdue total, inventory turnover, fill rate, on-time delivery %
25	backend/data/seed_briefing.sql	placeware_executive_briefings	1 pre-seeded daily briefing for March 4 2026 — gives EOS a warm start
26	backend/data/seed_kg.sql	kg_nodes, kg_edges	Core entity graph: top 10 customers, 6 suppliers, 20 SKU nodes + key edges
27	backend/data/seed_event_ledger.sql	event_ledger	~30 historical business events: order placed, payment received, stock alert, shipment cleared
Total: 27 mock data documents, 77 business-domain tables covered.

Go ahead and paste the EOS self-assessment reports whenever you're ready. I'll read each finding against the actual codebase and build implementation plans before we touch any data.