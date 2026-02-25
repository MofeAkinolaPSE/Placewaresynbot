# PlacewareBot Deployment Runbook (DigitalOcean)

Purpose: production deployment checklist for hosting app services on a DigitalOcean VPS Droplet with a managed database, while reducing cutover risk.

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
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_MODEL`
- `EMAIL_FROM`
- `EMAIL_PASS`
- `JWT_SECRET`
- `RATE_LIMIT`
- `CORS_ALLOW_ORIGINS`
- `WIDGET_SITE_KEYS`

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