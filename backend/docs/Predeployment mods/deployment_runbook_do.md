# PlacewareBot Deployment Runbook (DigitalOcean)

Purpose: production deployment checklist for hosting app services on a DigitalOcean VPS Droplet with a managed database, while reducing cutover risk.

## 0) Current Go-Live Operator Flow (VM + Sage Bridge)

This is the operational flow to use for the current Swarm deployment model in this repository.

1. Prepare secrets and environment files
- VM host: create and validate `backend/.env` from `backend/.env.example`.
- Sage Windows host: create and validate `sage-bridge/.env` from `sage-bridge/.env.example`.
- Ensure these key pairs match exactly:
  - `backend/.env` `SAGE_BRIDGE_KEY` == `sage-bridge/.env` `BRIDGE_API_KEY`
  - `backend/.env` `SAGE_BRIDGE_WEBHOOK_SECRET` == `sage-bridge/.env` `SYNBOT_WEBHOOK_KEY`

2. Start Sage and the bridge on Windows host
- Open Sage 50 client first.
- From `sage-bridge/`, run:
  - `python main.py`

3. Bootstrap and deploy on Ubuntu VM host
- From repo root, run:
  - First install: `sudo bash deploy/start-stack.sh --first-run --install-deps`
  - Rerun/redeploy: `sudo bash deploy/start-stack.sh --redeploy`

4. Connectivity gate (required by default in first-run)
- On Sage Windows host run:
  - `python test_connectivity.py --skip-write`
- `deploy/start-stack.sh` enforces a phase-4 confirmation gate before final completion.

5. Optional trusted TLS cutover
- Keep self-signed default for immediate go-live.
- Switch to trusted certificate when DNS/public routing is ready:
  - `sudo bash deploy/setup-letsencrypt.sh [domain] [email]`

6. Rollback commands
- `docker stack ps placeware`
- `docker service logs placeware_backend --tail 80`
- `docker service logs placeware_frontend --tail 40`
- `docker stack rm placeware`

## 1) Target Architecture
- App host: DigitalOcean Droplet (Ubuntu LTS), running FastAPI as a systemd service.
- Reverse proxy: Nginx (TLS termination + request limits).
- Database: DigitalOcean Managed PostgreSQL.
- Secrets/config: environment variables in systemd environment file.
- CI/CD (recommended): build + test in CI, deploy artifact to Droplet.

## 2) Critical Compatibility Note (Read First)
- Current backend data access uses Supabase SDK/table APIs (`supabase.table(...).execute()`) and expects `SUPABASE_URL`/`SUPABASE_KEY`.
- A plain DigitalOcean Managed PostgreSQL instance does not provide Supabase REST/Auth APIs.
- Before production cutover, choose one path:
  1. Keep Supabase as the runtime backend (fastest path), OR
  2. Refactor data layer from Supabase SDK to direct PostgreSQL access (SQLAlchemy/psycopg), then deploy on DO Managed PostgreSQL.
- Do not schedule production go-live on DO Managed PostgreSQL until this decision is completed and tested.

## 3) Provisioning Checklist

### Droplet
- [ ] Ubuntu LTS created (2+ vCPU, 4+ GB RAM for MVP).
- [ ] SSH keys configured; password login disabled.
- [ ] Firewall/UFW enabled (`22`, `80`, `443` only).
- [ ] Automatic security updates enabled.

### Managed PostgreSQL
- [ ] Cluster created in same region as Droplet.
- [ ] Trusted sources/VPC networking configured.
- [ ] TLS required (`sslmode=require` or stronger).
- [ ] Connection pool sizing and max connections documented.
- [ ] Backups enabled + retention policy confirmed.

### DNS/TLS
- [ ] DNS A record points to Droplet.
- [ ] TLS cert provisioned (Let’s Encrypt).
- [ ] HTTPS redirect and HSTS enabled.

## 4) Application Configuration (Env Contract)

## Required Runtime Variables (current codebase)
- `DATABASE_URL` (preferred when running against Postgres directly)
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_MODEL`
- `EMAIL_FROM`
- `EMAIL_PASS`
- `JWT_SECRET`
- `RATE_LIMIT`
- `CORS_ALLOW_ORIGINS`
- `WIDGET_SITE_KEYS`

Note: `SUPABASE_URL` / `SUPABASE_KEY` are optional and only required if you intend to run against a hosted Supabase project (REST/Auth APIs). The codebase supports direct Postgres via `DATABASE_URL` and the `LocalDBClient` compatibility layer.

## Additional Production Variables (recommended)
- `PYTHONUNBUFFERED=1`
- `LOG_LEVEL=INFO`
- `ENVIRONMENT=production`

## If migrating away from Supabase SDK to DO PostgreSQL
- Add `DATABASE_URL` (with TLS):
  - `postgresql://<user>:<pass>@<host>:<port>/<db>?sslmode=require`
- Add migration/ORM variables as needed by chosen data layer.

## 5) Database Migration Procedure

### For current Supabase-based runtime
- [ ] Apply incremental SQL migrations in order (`000`..latest) in staging.
- [ ] Validate key objects:
  - `placeware_orders.source`
  - `placeware_orders.lead_id`
  - `placeware_tracking`
- [ ] Promote to production with same migration set.

### For DO PostgreSQL runtime (after data-layer refactor)
- [ ] Run schema bootstrap + incremental migrations on DO cluster.
- [ ] Run smoke tests for `/submit_lead`, `/submit_order`, `/track/{tracking_id}`, `/chat`.
- [ ] Validate RLS/auth approach replacement if Supabase auth is removed.

## 6) Service Deployment (Droplet)

### Build + install
- [ ] Create Python venv and install `backend/requirements.txt`.
- [ ] Place env file at `/etc/placewarebot/backend.env` (root-only read).
- [ ] Create systemd unit for app service.

### systemd unit (example)
- Service should run `uvicorn app:app --host 0.0.0.0 --port 8000` from `backend` directory.
- Restart policy: `on-failure`.
- Include `EnvironmentFile=/etc/placewarebot/backend.env`.

### Nginx
- [ ] Proxy `/` to `127.0.0.1:8000`.
- [ ] Set request body limits and timeout.
- [ ] Add rate-limit zone for public endpoints.

## 7) Pre-Go-Live Validation
- [ ] Health check: `GET /` returns success.
- [ ] Auth flows: token/refresh/logout successful.
- [ ] Lead capture: `/submit_lead` stores row + logs notification path.
- [ ] Order flow: `/submit_order` creates order + tracking + audit event.
- [ ] Tracking: `/track/{id}` resolves persisted data.
- [ ] Chat path returns response and stores chat history.
- [ ] Alerting/logging wired to centralized sink.

## 8) Rollback Plan
- [ ] Keep previous app release artifact on host.
- [ ] Use blue/green or versioned systemd target where possible.
- [ ] DB migrations must be forward-safe; avoid destructive schema changes without backup.
- [ ] Validate restore drill from managed DB backup snapshot.

## 9) Operations Notes
- Keep app stateless; do not store critical workflow state on droplet disk.
- Rotate secrets on schedule; avoid credentials in repo or logs.
- Track deployment changes in `backend/docs/workflow_incomplete_tracker.md` update log.

## 10) Immediate Next Actions
1. Decide production DB strategy: keep Supabase vs migrate to direct DO PostgreSQL access.
2. If migrating, create a dedicated “Supabase-to-Postgres data layer” workstream before go-live.
3. Execute staging dry-run with full migration + workflow smoke tests.


---
official deployment strategy research 

this is the correct strategic lens.
DigitalOcean already provides several “PaaS-like” features on top of raw droplets. If we use them intelligently, we reduce complexity, improve reliability, and avoid over-engineering.
Below is a clean industry comparison and then a DigitalOcean-optimized Synbot deployment roadmap.
1️⃣ What DigitalOcean Already Provides (Use First)
✅ Compute

Droplets (VPS)
Vertical scaling
Snapshots
Backups (automated, paid add-on)

We use this as base layer.
✅ Managed Database (Very Important)
DigitalOcean Managed PostgreSQL:

Automated backups
Replication
Failover
Encryption at rest
Metrics
No DB container maintenance

For an ERP/CRM hybrid like Synbot:
This is strongly recommended over self-hosted Postgres.
Cost tradeoff:
More expensive than containerized Postgres
But drastically safer and production-ready.
Verdict:
Use Managed DB in production.
✅ Managed Redis
DigitalOcean offers managed Redis.
Synbot uses:

Memory layer
Agent state
Queue systems
Cache

Using managed Redis removes:

Persistence config
Eviction tuning
Replication management

Verdict:
Use DO Managed Redis if budget allows.
✅ DigitalOcean Load Balancer
If we scale beyond one droplet:

Built-in L4/L7 load balancing
Health checks
SSL termination option

This can reduce Traefik complexity later.
Early stage:
Traefik alone is fine.
Growth stage:
Use DO Load Balancer in front of droplets.
✅ DigitalOcean Container Registry
Instead of Docker Hub:

Private registry
Closer to droplet (lower latency)
Secure
Integrated auth

Use this for CI/CD pipeline.
✅ Monitoring & Insights
DigitalOcean provides:

CPU monitoring
Memory monitoring
Disk usage
Basic alerts

This replaces Prometheus early on.
✅ VPC (Virtual Private Cloud)
Critical feature.
You can:

Keep database private
Keep Redis private
Only expose droplet to public internet

Industry standard practice:
Database should NOT be public-facing.
2️⃣ Where We Should Still Use External Tools
Even with DO features, these remain valuable:
NeedBest OptionTLS + HTTPSTraefik or DO LB SSLWAF + DDoSCloudflareUptime MonitoringUptime RobotCI/CDGitHub ActionsLog aggregationLightweight Loki or external SaaS
3️⃣ What We Should NOT Do (Avoid Overengineering)
❌ Run Postgres in Docker in production
❌ Expose internal service ports
❌ Rely only on Watchtower auto-updates
❌ Skip backup validation
❌ Deploy everything on one environment forever
4️⃣ Optimized Synbot Deployment Strategy (DigitalOcean-Centric)
Now I’ll redefine the roadmap using maximum in-house capabilities first.
Phase 0 — Application Hardening (Before Infra)
Synbot must:

Use environment variables for config
Support external DB and Redis URLs
Include /health endpoint
Structured logs
Stateless containers
Separate service roles (API, worker, scheduler)

This ensures infrastructure flexibility.
Phase 1 — Secure Infrastructure Base
Create:

1 Production Droplet (Ubuntu 22.04)
Enable Backups (DO automated)
Place inside VPC
SSH key-only
Disable root login
UFW allow:

  * 22
  * 80
  * 443
No database on this droplet.
Phase 2 — Managed State Layer (Critical)
Provision:

Managed PostgreSQL (private network only)
Managed Redis (private network only)

Configure:

Allow access only from droplet VPC
Enable automated backups
Set alerting thresholds

This gives:

Failover
Backup safety
Encryption
Operational reliability

Phase 3 — Container Runtime Layer
On droplet:

Install Docker
Install Docker Compose
Connect app container to:

  * Managed DB
  * Managed Redis
Deploy:

Synbot API container
Synbot Worker container
Traefik reverse proxy

Only expose:

80
443

No direct app ports exposed.
Phase 4 — TLS Strategy
Two options:
Option A (Lean):
Traefik + Let’s Encrypt
Option B (Scale):
DigitalOcean Load Balancer + Managed SSL
Early stage:
Use Traefik.
When scaling horizontally:
Move SSL to DO Load Balancer.
Phase 5 — CI/CD Strategy (Controlled)
Instead of Watchtower:

GitHub Actions:

   * Build Docker image
   * Push to DO Container Registry

SSH deploy script:

   * Pull image
   * docker compose up -d

Manual approval before prod deploy

This avoids uncontrolled automatic updates.
Phase 6 — Observability
Use DigitalOcean:

Insights (CPU, memory)
Alert policies

Add:

Basic structured log retention
Uptime Robot external monitor

Later stage:
Add log aggregation service.
Phase 7 — Edge Protection
Add Cloudflare:

DNS
Rate limiting
Basic WAF
Bot mitigation

This protects AI endpoints from abuse.
5️⃣ Final Recommended Stack for Synbot
Layered Architecture:
Edge:
Cloudflare (optional but recommended)
Traffic:
Traefik (or DO Load Balancer later)
Compute:
DigitalOcean Droplet
State:
Managed PostgreSQL
Managed Redis
Registry:
DigitalOcean Container Registry
Monitoring:
DigitalOcean Insights + Uptime Robot
Backups:
DO Managed DB backups
Droplet snapshots
6️⃣ Cost Efficiency Strategy
If budget is tight:
Start with:

1 droplet
Managed Postgres only
Self-hosted Redis in Docker (temporary)
No DO Load Balancer yet

Upgrade path:
1️⃣ Add managed Redis
2️⃣ Add DO Load Balancer
3️⃣ Add secondary droplet
4️⃣ Move to multi-region
Final Conclusion
Yes — we can absolutely leverage DigitalOcean in-house features to reduce complexity and increase production reliability.
For Synbot (ERP/CRM hybrid + AI agents), the most critical upgrade from the video method is:
→ Use Managed Database
→ Use VPC isolation
→ Use DO monitoring
→ Replace Watchtower with CI/CD
With that, you’re operating at serious SaaS-grade deployment standards — not just VPS hobby level.
-----
## Sage Data Dump — Re-upload to the Client's ACE Instance

Purpose: load the fully processed Sage 50 dataset (1.11M rows across 18 tables,
as of 2026-07-07) into the client's server instance so their ACE runs on the
same cleaned data as the local build — including the PO/AP de-duplication
merge, real AR due dates, customer attribution repair, credit limits, item
costs/expiry dates, customer profitability, and the enriched CRM customer
master.

### What the dump contains

- File: `data-assimilation/dumps/ace_sage_data_dump_2026-07-07.sql.gz` (~15 MB)
- Prep script: `data-assimilation/dumps/ace_sage_data_restore_prep.sql`
- Tables (data-only, plain SQL COPY): all 15 `sage_*_snapshot` tables,
  `customers` (enriched CRM master), `reconciliation_tracking`,
  `placeware_inventory_events`.
- The dump does NOT contain schema. Tables, columns, and views come from the
  code migrations — which is why step 1 below matters.

### Step 1 — Deploy the latest code first (required)

The dump depends on schema created by migrations up to 096:

- 093 `v_pl_monthly` view (monthly P&L)
- 094 `v_budget_actuals_monthly` view (budget actuals)
- 095 `sage_customers_snapshot` enrichment columns (address/city/terms/…)
- 096 `sage_customer_sales_snapshot` table

On the client host, pull the latest repo and redeploy so migrations run:

```bash
git pull
sudo bash deploy/start-stack.sh --redeploy      # Swarm model
# or for the compose model:
docker compose -f backend/docker-compose.yml up -d --build
```

Confirm the backend is healthy before continuing:

```bash
docker ps --format '{{.Names}}: {{.Status}}'    # backend + db must be healthy
```

### Step 2 — Copy the dump files to the client host

```bash
scp data-assimilation/dumps/ace_sage_data_dump_2026-07-07.sql.gz \
    data-assimilation/dumps/ace_sage_data_restore_prep.sql \
    user@CLIENT_HOST:/tmp/
```

### Step 3 — Load the data

Identify the postgres container name on the client host (examples below use
`backend-db-1`; under Swarm it may be `placeware_db.1.<id>` — find it with
`docker ps`). The database name is `synbot_demo` unless the client `.env`
overrides `DATABASE_URL`.

```bash
# 3a. Clear the target tables (idempotent — safe to re-run)
docker exec -i backend-db-1 psql -U postgres -d synbot_demo \
    < /tmp/ace_sage_data_restore_prep.sql

# 3b. Load the dump (takes ~1-3 minutes for the 915K GL rows)
gunzip -c /tmp/ace_sage_data_dump_2026-07-07.sql.gz | \
    docker exec -i backend-db-1 psql -U postgres -d synbot_demo
```

Notes:
- The prep script truncates `customers` with CASCADE (it is referenced by
  `crm_activities` / `customer_360`). On a fresh instance those are empty; on
  a re-run any CRM activity rows tied to old customer ids are also cleared.
- Both steps are transactional per statement; if 3b fails midway, simply
  re-run 3a then 3b.

### Step 4 — Restart the backend to clear caches

KPI and dashboard endpoints cache for up to 10 minutes; restart to serve the
new data immediately:

```bash
docker restart chat-backend.v1        # compose model
# or: docker service update --force placeware_backend   # Swarm model
```

### Step 5 — Verify

DB-level spot checks:

```bash
docker exec backend-db-1 psql -U postgres -d synbot_demo -c "
SELECT
 (SELECT COUNT(*) FROM sage_gl_detail_snapshot)                          AS gl_detail,   -- 914,992
 (SELECT COUNT(*) FROM sage_ar_snapshot)                                 AS ar_rows,     -- 101,086
 (SELECT COUNT(*) FROM sage_ar_snapshot WHERE due_date IS NOT NULL)      AS ar_with_due, -- 33,725
 (SELECT COUNT(*) FROM sage_purchase_orders_snapshot)                    AS pos,         -- 1,180
 (SELECT COUNT(*) FROM customers)                                        AS customers,   -- 1,538
 (SELECT COUNT(*) FROM customers WHERE credit_limit > 0)                 AS w_credit,    -- 1,093
 (SELECT COUNT(*) FROM sage_customer_sales_snapshot)                     AS cust_sales;  -- 1,093
"
```

API-level checks (get a token via POST /token with the admin credentials from
the client `.env`, then):

- `GET /analytics/kpis` — cash ≈ ₦336.6M, AR ≈ ₦18.06B, AP ≈ ₦6.95B
- `GET /finance/ar/aging` — four non-zero buckets, ~1,600 customer rows
- `GET /finance/credit/risk` — ~1,008 customers scored
- `GET /procurement/purchase-orders/summary` — 1,180 total / 1,175 overdue
- `GET /dashboard/inventory` — 791 SKUs, ~146 active out-of-stock
- CRM → Customer Accounts — 1,538 customers with city/terms/credit limit;
  the 360 view (eye icon) shows receivables, profitability, and top items.

### Regenerating the dump after new local changes

From the local dev machine:

```powershell
docker exec backend-db-1 sh -c "pg_dump -U postgres -d synbot_demo --data-only --no-owner --no-privileges -t sage_coa_snapshot -t sage_vendors_snapshot -t sage_customers_snapshot -t sage_items_snapshot -t sage_inventory_snapshot -t sage_purchase_orders_snapshot -t sage_ar_snapshot -t sage_ap_snapshot -t sage_invoice_lines_snapshot -t sage_inv_transactions_snapshot -t sage_gl_snapshot -t sage_gl_detail_snapshot -t sage_cash_register_snapshot -t sage_gl_account_summary_snapshot -t sage_customer_sales_snapshot -t customers -t reconciliation_tracking -t placeware_inventory_events | gzip > /tmp/ace_sage_data_dump.sql.gz"
docker cp backend-db-1:/tmp/ace_sage_data_dump.sql.gz "data-assimilation\dumps\ace_sage_data_dump_$(Get-Date -Format yyyy-MM-dd).sql.gz"
```

Update the filename in steps 2-3 accordingly.
