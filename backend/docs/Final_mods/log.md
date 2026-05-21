oeakin@PlacewareBot:~/Placewaresynbot/backend$ sudo docker service logs placeware_db --tail 50
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:07.715 UTC [122] STATEMENT:  INSERT INTO public.placeware_incident_log (incident_key, component, severity, status, summary, details, correlation_id, detected_at) VALUES ('finance_dashboard:Financial snapshot tables are empty.','finance_dashboard','critical','open','Financial snapshot tables are empty.','{"diagnostics": {"healthy": false, "severity": "critical", "summary": "Financial snapshot tables are empty.", "checks": [{"check": "ar_snapshot_rows", "ok": false, "value": 0}, {"check": "ap_snapshot_rows", "ok": false, "value": 0}, {"check": "gl_snapshot_rows", "ok": false, "value": 0}, {"check": "kpis_non_zero", "ok": false, "value": {"ar": {"total_amount": 0, "total_balance": 0, "overdue_count": 0}, "ap": {"total_amount": 0, "total_balance": 0, "overdue_count": 0}, "cash": null, "total_revenue": 0.0, "total_cost": 0.0}}, {"check": "latest_gl_batch_readable", "ok": false, "value": 0}], "failed_checks": [{"check": "ar_snapshot_rows", "ok": false, "value": 0}, {"check": "ap_snapshot_rows", "ok": false, "value": 0}, {"check": "gl_snapshot_rows", "ok": false, "value": 0}, {"check": "kpis_non_zero", "ok": false, "value": {"ar": {"total_amount": 0, "total_balance": 0, "overdue_count": 0}, "ap": {"total_amount": 0, "total_balance": 0, "overdue_count": 0}, "cash": null, "total_revenue": 0.0, "total_cost": 0.0}}, {"check": "latest_gl_batch_readable", "ok": false, "value": 0}], "metrics": {"ar_rows": 0, "ap_rows": 0, "gl_rows": 0}}}'::jsonb,'ec7f1edd-16ce-47cc-b2be-82f12a642375','2026-05-21T20:13:07Z') RETURNING *
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:07.771 UTC [122] ERROR:  relation "public.placeware_inventory_snapshot" does not exist at character 44
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:07.771 UTC [122] STATEMENT:  SELECT sku, current_qty, safety_stock FROM public.placeware_inventory_snapshot WHERE current_qty < 10
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:07.774 UTC [122] ERROR:  relation "public.placeware_inventory_snapshot" does not exist at character 53
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:07.774 UTC [122] STATEMENT:  SELECT sku, batch_id, current_qty, expiry_date FROM public.placeware_inventory_snapshot WHERE expiry_date < '2026-06-20T20:13:07.774110' AND current_qty > 0
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:07.784 UTC [122] ERROR:  relation "public.placeware_ar_ledger" does not exist at character 62
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:07.784 UTC [122] STATEMENT:  SELECT customer_id, customer_name, amount, invoice_date FROM public.placeware_ar_ledger
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.411 UTC [123] ERROR:  relation "public.placeware_inventory_snapshot" does not exist at character 44
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.411 UTC [123] STATEMENT:  SELECT sku, current_qty, safety_stock FROM public.placeware_inventory_snapshot WHERE current_qty < 10
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.420 UTC [259] ERROR:  relation "public.placeware_inventory_snapshot" does not exist at character 44
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.420 UTC [259] STATEMENT:  SELECT sku, current_qty, safety_stock FROM public.placeware_inventory_snapshot WHERE current_qty < 10
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.421 UTC [123] ERROR:  relation "public.placeware_inventory_snapshot" does not exist at character 53
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.421 UTC [123] STATEMENT:  SELECT sku, batch_id, current_qty, expiry_date FROM public.placeware_inventory_snapshot WHERE expiry_date < '2026-06-20T20:13:11.420868' AND current_qty > 0
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.424 UTC [123] ERROR:  relation "public.placeware_ar_ledger" does not exist at character 62
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.424 UTC [123] STATEMENT:  SELECT customer_id, customer_name, amount, invoice_date FROM public.placeware_ar_ledger
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.424 UTC [259] ERROR:  relation "public.placeware_inventory_snapshot" does not exist at character 53
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.424 UTC [259] STATEMENT:  SELECT sku, batch_id, current_qty, expiry_date FROM public.placeware_inventory_snapshot WHERE expiry_date < '2026-06-20T20:13:11.423721' AND current_qty > 0
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.428 UTC [259] ERROR:  relation "public.placeware_ar_ledger" does not exist at character 62
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.428 UTC [259] STATEMENT:  SELECT customer_id, customer_name, amount, invoice_date FROM public.placeware_ar_ledger
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.506 UTC [113] ERROR:  relation "public.sage_ar_snapshot" does not exist at character 22
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.506 UTC [113] STATEMENT:  SELECT COUNT(*) FROM public.sage_ar_snapshot
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.519 UTC [113] ERROR:  relation "public.sage_ap_snapshot" does not exist at character 22
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.519 UTC [113] STATEMENT:  SELECT COUNT(*) FROM public.sage_ap_snapshot
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.529 UTC [113] ERROR:  relation "public.sage_gl_snapshot" does not exist at character 22
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.529 UTC [113] STATEMENT:  SELECT COUNT(*) FROM public.sage_gl_snapshot
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.541 UTC [113] ERROR:  relation "public.placeware_kpi_promotions" does not exist at character 93
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.541 UTC [113] STATEMENT:  SELECT domain,batch_id,job_id,promoted_at,quality_score,rejection_rate,promoted_reason FROM public.placeware_kpi_promotions WHERE domain = 'sage' LIMIT 1
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.547 UTC [113] ERROR:  relation "public.sage_gl_snapshot" does not exist at character 22
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.547 UTC [113] STATEMENT:  SELECT batch_id FROM public.sage_gl_snapshot ORDER BY imported_at DESC LIMIT 1
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.560 UTC [113] ERROR:  relation "public.placeware_incident_log" does not exist at character 13
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.560 UTC [113] STATEMENT:  INSERT INTO public.placeware_incident_log (incident_key, component, severity, status, summary, details, correlation_id, detected_at) VALUES ('finance_dashboard:Financial snapshot tables are empty.','finance_dashboard','critical','open','Financial snapshot tables are empty.','{"diagnostics": {"healthy": false, "severity": "critical", "summary": "Financial snapshot tables are empty.", "checks": [{"check": "ar_snapshot_rows", "ok": false, "value": 0}, {"check": "ap_snapshot_rows", "ok": false, "value": 0}, {"check": "gl_snapshot_rows", "ok": false, "value": 0}, {"check": "kpis_non_zero", "ok": false, "value": {"ar": {"total_amount": 0, "total_balance": 0, "overdue_count": 0}, "ap": {"total_amount": 0, "total_balance": 0, "overdue_count": 0}, "cash": null, "total_revenue": 0.0, "total_cost": 0.0}}, {"check": "latest_gl_batch_readable", "ok": false, "value": 0}], "failed_checks": [{"check": "ar_snapshot_rows", "ok": false, "value": 0}, {"check": "ap_snapshot_rows", "ok": false, "value": 0}, {"check": "gl_snapshot_rows", "ok": false, "value": 0}, {"check": "kpis_non_zero", "ok": false, "value": {"ar": {"total_amount": 0, "total_balance": 0, "overdue_count": 0}, "ap": {"total_amount": 0, "total_balance": 0, "overdue_count": 0}, "cash": null, "total_revenue": 0.0, "total_cost": 0.0}}, {"check": "latest_gl_batch_readable", "ok": false, "value": 0}], "metrics": {"ar_rows": 0, "ap_rows": 0, "gl_rows": 0}}}'::jsonb,'8fc89e20-27a7-451d-93a9-a22c7b4e4f23','2026-05-21T20:13:11Z') RETURNING *
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.629 UTC [113] ERROR:  relation "public.placeware_inventory_snapshot" does not exist at character 44
placeware_db.1.wojxa2hs5vep@PlacewareBot    | 
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.629 UTC [113] STATEMENT:  SELECT sku, current_qty, safety_stock FROM public.placeware_inventory_snapshot WHERE current_qty < 10
placeware_db.1.wojxa2hs5vep@PlacewareBot    | PostgreSQL Database directory appears to contain a database; Skipping initialization
placeware_db.1.wojxa2hs5vep@PlacewareBot    | 
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.642 UTC [113] ERROR:  relation "public.placeware_inventory_snapshot" does not exist at character 53
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.642 UTC [113] STATEMENT:  SELECT sku, batch_id, current_qty, expiry_date FROM public.placeware_inventory_snapshot WHERE expiry_date < '2026-06-20T20:13:11.639106' AND current_qty > 0
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.650 UTC [113] ERROR:  relation "public.placeware_ar_ledger" does not exist at character 62
placeware_db.1.wojxa2hs5vep@PlacewareBot    | 2026-05-21 20:27:46.021 UTC [7] LOG:  starting PostgreSQL 18.4 (Debian 18.4-1.pgdg13+1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 14.2.0-19) 14.2.0, 64-bit
placeware_db.1.wojxa2hs5vep@PlacewareBot    | 2026-05-21 20:27:46.022 UTC [7] LOG:  listening on IPv4 address "0.0.0.0", port 5432
placeware_db.1.wojxa2hs5vep@PlacewareBot    | 2026-05-21 20:27:46.023 UTC [7] LOG:  listening on IPv6 address "::", port 5432
placeware_db.1.wojxa2hs5vep@PlacewareBot    | 2026-05-21 20:27:46.034 UTC [7] LOG:  listening on Unix socket "/var/run/postgresql/.s.PGSQL.5432"
placeware_db.1.wojxa2hs5vep@PlacewareBot    | 2026-05-21 20:27:46.054 UTC [33] LOG:  database system was shut down at 2026-05-21 20:27:43 UTC
placeware_db.1.wojxa2hs5vep@PlacewareBot    | 2026-05-21 20:27:46.070 UTC [7] LOG:  database system is ready to accept connections
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:13:11.650 UTC [113] STATEMENT:  SELECT customer_id, customer_name, amount, invoice_date FROM public.placeware_ar_ledger
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:14:35.357 UTC [74] LOG:  checkpoint starting: time
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:14:39.823 UTC [74] LOG:  checkpoint complete: wrote 43 buffers (0.3%), wrote 3 SLRU buffers; 0 WAL file(s) added, 0 removed, 0 recycled; write=4.397 s, sync=0.030 s, total=4.466 s; sync files=12, longest=0.008 s, average=0.003 s; distance=318 kB, estimate=318 kB; lsn=0/1BEF6E0, redo lsn=0/1BEF650
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:17:01.319 UTC [6] LOG:  received fast shutdown request
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:17:01.330 UTC [6] LOG:  aborting any active transactions
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:17:01.331 UTC [259] FATAL:  terminating connection due to administrator command
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:17:01.331 UTC [123] FATAL:  terminating connection due to administrator command
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:17:01.331 UTC [122] FATAL:  terminating connection due to administrator command
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:17:01.337 UTC [113] FATAL:  terminating connection due to administrator command
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:17:01.347 UTC [6] LOG:  background worker "logical replication launcher" (PID 79) exited with exit code 1
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:17:01.351 UTC [74] LOG:  shutting down
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:17:01.359 UTC [74] LOG:  checkpoint starting: shutdown immediate
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:17:01.409 UTC [74] LOG:  checkpoint complete: wrote 0 buffers (0.0%), wrote 0 SLRU buffers; 0 WAL file(s) added, 0 removed, 0 recycled; write=0.001 s, sync=0.001 s, total=0.058 s; sync files=0, longest=0.000 s, average=0.000 s; distance=0 kB, estimate=286 kB; lsn=0/1BEF790, redo lsn=0/1BEF790
placeware_db.1.kdoaq3dbyqqh@PlacewareBot    | 2026-05-21 20:17:01.444 UTC [6] LOG:  database system is shut down
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:40.277 UTC [176] WARNING:  there is already a transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:40.286 UTC [176] WARNING:  there is no transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:40.291 UTC [176] WARNING:  there is already a transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:40.294 UTC [176] WARNING:  there is no transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:40.300 UTC [176] WARNING:  there is already a transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:40.303 UTC [176] WARNING:  there is no transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:40.308 UTC [176] WARNING:  there is already a transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:40.315 UTC [176] WARNING:  there is no transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:40.443 UTC [176] WARNING:  there is already a transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:40.488 UTC [176] WARNING:  there is no transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:40.496 UTC [176] WARNING:  there is already a transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:40.501 UTC [176] WARNING:  there is no transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:40.509 UTC [176] WARNING:  there is already a transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:40.513 UTC [176] WARNING:  there is no transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:40.987 UTC [176] WARNING:  there is already a transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:41.003 UTC [176] WARNING:  there is no transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:41.007 UTC [176] WARNING:  there is already a transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:41.015 UTC [176] WARNING:  there is no transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:41.020 UTC [176] WARNING:  there is already a transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:19:41.026 UTC [176] WARNING:  there is no transaction in progress
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:20:57.625 UTC [189] ERROR:  column "required_components" is of type jsonb but expression is of type text[] at character 467
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:20:57.625 UTC [189] HINT:  You will need to rewrite or cast the expression.
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:20:57.625 UTC [189] STATEMENT:  INSERT INTO public.placeware_capability_proposals (capability_name, problem, opportunity, required_components, integration_points, estimated_impact, confidence_score, signal_ids, status) VALUES ('Automated Recovery: finance_dashboard','Recurring failures detected in finance_dashboard: finance_dashboard: Financial snapshot tables are empty.','Implement automated recovery logic for finance_dashboard to reduce manual intervention and MTTR. Observed 3 occurrences.',ARRAY['health_monitor','auto_recovery_playbook','escalation_handler'],ARRAY['finance_dashboard_service','maintenance_agent','incident_log'],'Estimated 45 minutes/month saved in manual recovery time.',0.7,ARRAY['f3202fd4-2ad0-4b03-b729-ead4ed016258'],'proposed') RETURNING *
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:20:57.798 UTC [188] ERROR:  column "required_components" is of type jsonb but expression is of type text[] at character 467
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:20:57.798 UTC [188] HINT:  You will need to rewrite or cast the expression.
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:20:57.798 UTC [188] STATEMENT:  INSERT INTO public.placeware_capability_proposals (capability_name, problem, opportunity, required_components, integration_points, estimated_impact, confidence_score, signal_ids, status) VALUES ('Automated Recovery: finance_dashboard','Recurring failures detected in finance_dashboard: finance_dashboard: Financial snapshot tables are empty.','Implement automated recovery logic for finance_dashboard to reduce manual intervention and MTTR. Observed 4 occurrences.',ARRAY['health_monitor','auto_recovery_playbook','escalation_handler'],ARRAY['finance_dashboard_service','maintenance_agent','incident_log'],'Estimated 60 minutes/month saved in manual recovery time.',0.75,ARRAY['f3202fd4-2ad0-4b03-b729-ead4ed016258'],'proposed') RETURNING *
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:22:02.846 UTC [31] LOG:  checkpoint starting: time
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:23:46.839 UTC [31] LOG:  checkpoint complete: wrote 1011 buffers (6.2%), wrote 3 SLRU buffers; 0 WAL file(s) added, 0 removed, 1 recycled; write=103.005 s, sync=0.966 s, total=103.993 s; sync files=1159, longest=0.004 s, average=0.001 s; distance=8335 kB, estimate=8335 kB; lsn=0/24135C0, redo lsn=0/2413530
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:02.941 UTC [31] LOG:  checkpoint starting: time
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:05.300 UTC [31] LOG:  checkpoint complete: wrote 22 buffers (0.1%), wrote 1 SLRU buffers; 0 WAL file(s) added, 0 removed, 0 recycled; write=2.296 s, sync=0.032 s, total=2.360 s; sync files=17, longest=0.009 s, average=0.002 s; distance=30 kB, estimate=7504 kB; lsn=0/241AF20, redo lsn=0/241AEC8
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.679 UTC [7] LOG:  received fast shutdown request
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.687 UTC [7] LOG:  aborting any active transactions
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.688 UTC [202] FATAL:  terminating connection due to administrator command
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.688 UTC [205] FATAL:  terminating connection due to administrator command
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.689 UTC [190] FATAL:  terminating connection due to administrator command
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.690 UTC [204] FATAL:  terminating connection due to administrator command
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.692 UTC [203] FATAL:  terminating connection due to administrator command
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.695 UTC [200] FATAL:  terminating connection due to administrator command
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.696 UTC [188] FATAL:  terminating connection due to administrator command
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.699 UTC [201] FATAL:  terminating connection due to administrator command
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.702 UTC [191] FATAL:  terminating connection due to administrator command
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.704 UTC [189] FATAL:  terminating connection due to administrator command
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.706 UTC [178] FATAL:  terminating connection due to administrator command
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.706 UTC [187] FATAL:  terminating connection due to administrator command
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.708 UTC [186] FATAL:  terminating connection due to administrator command
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.718 UTC [7] LOG:  background worker "logical replication launcher" (PID 36) exited with exit code 1
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.758 UTC [31] LOG:  shutting down
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.764 UTC [31] LOG:  checkpoint starting: shutdown immediate
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.788 UTC [31] LOG:  checkpoint complete: wrote 0 buffers (0.0%), wrote 0 SLRU buffers; 0 WAL file(s) added, 0 removed, 0 recycled; write=0.001 s, sync=0.001 s, total=0.030 s; sync files=0, longest=0.000 s, average=0.000 s; distance=0 kB, estimate=6754 kB; lsn=0/241AFD0, redo lsn=0/241AFD0
placeware_db.1.rpn6ondlvlem@PlacewareBot    | 2026-05-21 20:27:43.834 UTC [7] LOG:  database system is shut down
