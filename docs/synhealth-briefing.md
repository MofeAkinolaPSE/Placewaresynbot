# SynHealth Technical Briefing
## Replicating Warebot Architecture for a Hospital Client (DRM Hope Software)

**Prepared from:** Warebot (PlacewareBot) — production codebase  
**Target project:** SynHealth  
**Audience:** AI coding agent (Copilot) onboarding into the SynHealth repo

---

## 1. What Warebot Is (Context for Comparison)

Warebot is a pharma distribution AI assistant built for Placeware. It runs fully on a local Ubuntu server (or VM) with Docker Compose. It connects to Sage 50 Peachtree 2013 (accounting software on a separate Windows machine) via a bridge service. Everything is self-hosted — no cloud dependency at runtime except DeepSeek API calls for the LLM and Supabase for the vector store.

SynHealth is the same architecture applied to a hospital. The client software is **DRM Hope** instead of Sage 50. The domain changes (patients, wards, pharmacy, billing) but the structural patterns are identical.

---

## 2. Overall Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│  LOCAL SERVER  (Ubuntu VM or Docker-capable desktop on hospital LAN)   │
│                                                                         │
│  ┌───────────────┐   ┌──────────────────┐   ┌─────────────────────┐   │
│  │  nginx        │   │  FastAPI backend  │   │  PostgreSQL +        │   │
│  │  (port 80/443)│──▶│  (port 8000)      │──▶│  pgvector           │   │
│  │  React SPA    │   │  uvicorn          │   │  (port 5432)        │   │
│  └───────────────┘   └──────────────────┘   └─────────────────────┘   │
│         │                     │                                         │
│         │              DeepSeek API (external, HTTPS only)             │
│         │                     │                                         │
│         │         ┌───────────────────────┐                            │
│         │         │  Hope Bridge Service  │  (port 7070)               │
│         │         │  Python + FastAPI     │                            │
│         │         │  Runs on Hope PC or   │                            │
│         │         │  same server          │                            │
│         │         └───────────────────────┘                            │
│                             │                                           │
│              ┌──────────────┘                                           │
│              ▼                                                           │
│   ┌────────────────────┐                                                │
│   │  DRM Hope Software │  (Windows PC on hospital LAN)                 │
│   │  Hospital DB/API   │                                                │
│   └────────────────────┘                                                │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Deployment Strategy (Local Server — Same as Warebot)

### 3.1 Docker Compose Stack

All services are defined in two files:
- `docker-compose.yml` — base dev/prod definition
- `docker-compose.prod.yml` — production overrides (multi-worker uvicorn, memory limits, log rotation)

**Run with:**
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**Services in the stack:**
| Service | Image | Role |
|---|---|---|
| `db` | Custom postgres:18 + pgvector | Primary database |
| `backend` | Custom python:3.11-slim | FastAPI API server |
| `frontend` | Custom nginx:1.27-alpine | Serves React SPA + reverse proxy |
| `certs-init` | alpine:3.19 | One-shot: generates self-signed TLS cert on first run |
| `prometheus` | prom/prometheus | Metrics scraping (loopback only) |
| `grafana` | grafana/grafana | Dashboards (loopback only) |

### 3.2 TLS (HTTPS) — Self-Signed on LAN

The certs-init service auto-generates a self-signed certificate into a named Docker volume (`ssl_certs`) on first `docker compose up`. nginx mounts it read-only.

```yaml
certs-init:
  image: alpine:3.19
  volumes:
    - ssl_certs:/etc/ssl/synhealth
  command:
    - /bin/sh
    - -c
    - |
      if [ ! -f /etc/ssl/synhealth/cert.pem ]; then
        apk add --no-cache openssl
        openssl req -x509 -nodes -newkey rsa:2048 \
          -keyout /etc/ssl/synhealth/key.pem \
          -out    /etc/ssl/synhealth/cert.pem \
          -days 825 \
          -subj '/CN=synhealth-internal/O=SynHealth/C=NG' \
          -addext 'subjectAltName=IP:127.0.0.1,DNS:localhost'
      fi
  restart: "no"
```

For production with a real domain: swap to Let's Encrypt (`certbot`) — update nginx.conf cert paths only.

### 3.3 Database Migrations

On container start, the entrypoint runs `python scripts/apply_migrations.py` **before** starting uvicorn. This script:
1. Creates a `schema_migrations` table if it doesn't exist
2. Reads all `.sql` files from `migrations/` in filename order
3. Skips already-applied files (idempotent)
4. Applies new ones in a single transaction per file

**Pattern for SynHealth:** Name migration files `000_`, `001_`, `002_` etc. The runner applies them in order on every deploy — safe to run repeatedly.

### 3.4 Entrypoint Pattern

```sh
#!/bin/sh
set -e
echo "[1/2] Running database migrations..."
python scripts/apply_migrations.py
echo "[2/2] Starting API server..."
exec "$@"    # passes CMD through — allows docker-compose.prod.yml to override uvicorn args
```

### 3.5 CI/CD (GitHub Actions → Self-Hosted Runner)

The deploy pipeline has 3 jobs:
1. **test** — runs `pytest -q` on ubuntu-latest
2. **security** — Bandit SAST + Trivy CVE scan (blocks deploy on CRITICAL CVEs)
3. **deploy** — runs on `[self-hosted, linux, synhealth-vm]` runner installed on the hospital server

**Security fix — secrets injection:**  
Never interpolate `${{ secrets.X }}` directly in `run:` scripts (shell injection risk).  
Always bind to `env:` block first:
```yaml
env:
  _JWT_SECRET: ${{ secrets.JWT_SECRET }}
run: |
  printf 'JWT_SECRET=%s\n' "$_JWT_SECRET" >> .env
```

**Install runner on the server:**
```bash
# On the hospital server
mkdir actions-runner && cd actions-runner
curl -o runner.tar.gz -L https://github.com/actions/runner/releases/download/v2.x.x/actions-runner-linux-x64-2.x.x.tar.gz
tar xzf runner.tar.gz
./config.sh --url https://github.com/YOUR_ORG/synhealth --token <TOKEN> --labels synhealth-vm
sudo ./svc.sh install && sudo ./svc.sh start
```

---

## 4. Embedding + RAG Pipeline (Replicate Exactly)

This is the core "brain" of the chat assistant. Copy verbatim from Warebot.

### 4.1 Stack

| Layer | Tech | Detail |
|---|---|---|
| Model | `sentence-transformers/all-MiniLM-L6-v2` | 384-dim, ~23 MB |
| Runtime format | ONNX + `onnxruntime` | No torch/transformers at runtime |
| Tokenizer | HuggingFace `tokenizers` (Rust) | `tokenizer.json`, max 128 tokens |
| Vector store | PostgreSQL + `pgvector` | `vector(384)` column, cosine similarity |
| Retrieval | Supabase-compatible RPC `match_documents` | threshold 0.78, top-k 3 |

### 4.2 Dockerfile Model Baking (Key Pattern)

The ONNX model is downloaded at **build time**, not runtime. Zero startup latency, works fully offline:

```dockerfile
FROM python:3.11-slim AS model_downloader
RUN apt-get update && apt-get install -y wget ca-certificates
WORKDIR /models
RUN wget -q "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx" -O model.onnx
RUN wget -q "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/tokenizer.json" -O tokenizer.json

FROM python:3.11-slim AS runtime
COPY --from=model_downloader /models/ ./src/models/
```

### 4.3 Inference Flow

```
query string
  → tokenizer.json (pad/truncate to 128 tokens)
  → ONNX session (onnxruntime, 2 intra-op threads)
  → mean pool over token dimension (if no sentence_embedding output)
  → L2 normalize → list[float] of len 384
  → match_documents RPC → top-k (question, answer) rows
  → inject as context into DeepSeek prompt
```

### 4.4 Supabase RPC (SQL function required in DB)

```sql
CREATE OR REPLACE FUNCTION match_documents(
  query_embedding vector(384),
  match_threshold float,
  match_count int
)
RETURNS TABLE(question text, answer text, similarity float)
LANGUAGE plpgsql AS $$
BEGIN
  RETURN QUERY
  SELECT q.question, q.answer,
         1 - (q.embedding <=> query_embedding) AS similarity
  FROM qna q
  WHERE 1 - (q.embedding <=> query_embedding) > match_threshold
  ORDER BY q.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;
```

For SynHealth, the `qna` table becomes hospital-domain Q&A: ward procedures, medication policies, admission FAQs, etc.

---

## 5. LLM Integration (DeepSeek)

### 5.1 Pattern

```python
class DeepSeek:
    def generate_response(self, context: str, question: str, instruction: str | None = None) -> str:
        system_msg = instruction or f"You are {BOT_NAME}, an AI assistant for {BOT_BRAND}..."
        user_content = f"Context:\n{context}\n\nQuestion: {question}"
        # POST to https://api.deepseek.com/v1/chat/completions
```

### 5.2 For SynHealth

- Change `BOT_NAME = "SynHealth"`, `BOT_BRAND = "SynHealth Hospital System"`
- Add a medical disclaimer constant (equivalent of `NAFDAC_DISCLAIMER`):
  ```python
  MEDICAL_DISCLAIMER = (
      "This response is for general informational purposes only and does not "
      "constitute medical advice. Always consult a qualified clinician for "
      "patient-specific decisions."
  )
  ```
- Append disclaimer to every response in the `generate_response` wrapper

---

## 6. The Bridge Pattern — How We Connect to External Software

This is the critical section for DRM Hope integration.

### 6.1 Architecture Overview

Warebot connects to Sage 50 (accounting software on a Windows PC) via a **Bridge Service** — a separate FastAPI app that runs on the Windows machine and exposes a REST API. SynBot calls it over the LAN.

```
SynHealth backend (Docker, port 8000)
    │
    │  HTTP GET/POST  (LAN, port 7070)
    ▼
Hope Bridge Service (Python FastAPI, Windows machine or same server)
    │
    ├── ODBC → DRM Hope database (read-only queries)
    └── SDK/API → DRM Hope SDK (writes, if available)
```

### 6.2 Sage Bridge — Techniques Used (Map to Hope)

**Two access layers — use the same split for Hope:**

| Layer | Sage 50 | DRM Hope equivalent |
|---|---|---|
| **Read** | `pyodbc` → Pervasive PSQL ODBC tables | `pyodbc` → Hope ODBC DSN **or** Hope's REST API (if licensed) |
| **Write** | `pythonnet` → `Sage.Peachtree.API.dll` (.NET SDK) | Hope SDK/API (investigate what Hope exposes — ODBC, COM, REST, or HL7 FHIR) |

**ODBC read pattern (copy for Hope):**
```python
# odbc_client.py
import pyodbc

def get_connection():
    dsn = settings.HOPE_ODBC_DSN  # registered in Windows ODBC Data Source Administrator
    return pyodbc.connect(f"DSN={dsn};Trusted_Connection=yes")

def fetch_patients(limit=100, offset=0):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT TOP ? * FROM PATIENT ORDER BY PatientID OFFSET ? ROWS", limit, offset)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
```

**Key tables to discover in Hope (run this on first site visit):**
```sql
-- In SQL Server Management Studio or via ODBC:
SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'
-- Map to: patients, admissions, wards, pharmacy_orders, billing, staff, appointments
```

### 6.3 Change Detection — File Watcher / Polling

For Sage we watched `.DAT` file modification timestamps. For DRM Hope (SQL Server backend):

**Option A — Polling (simpler, same as Sage watcher):**
```python
# Poll a high-watermark timestamp column every 60s
SELECT * FROM PATIENT WHERE UpdatedAt > :last_checked
```

**Option B — SQL Server Change Tracking (better, if Hope uses MSSQL):**
```sql
-- Enable on Hope DB:
ALTER DATABASE HopeDB SET CHANGE_TRACKING = ON (CHANGE_RETENTION = 2 DAYS)
ALTER TABLE PATIENT ENABLE CHANGE_TRACKING
-- Then query: SELECT * FROM CHANGETABLE(CHANGES PATIENT, :last_sync_version) AS ct
```

When a change is detected → push a webhook to the SynHealth backend:
```python
httpx.post(
    f"{settings.SYNHEALTH_WEBHOOK_URL}/hope/webhook",
    json={"entity": "patient", "action": "update", "ids": [...]},
    headers={"X-Bridge-Key": settings.BRIDGE_API_KEY},
    timeout=10
)
```

### 6.4 Bridge Security

```python
# All bridge endpoints require this header
def verify_bridge_key(x_bridge_key: str = Header(...)):
    if not hmac.compare_digest(x_bridge_key, settings.BRIDGE_API_KEY):
        raise HTTPException(status_code=403, detail="Invalid bridge key")
```

Shared secret set identically in both `.env` files (bridge + SynHealth backend).

### 6.5 Bridge as Windows Service (NSSM)

The Sage bridge installs as a Windows service so it survives reboots without login. Same pattern for Hope bridge:

```powershell
# install-service.ps1 — run as Administrator on Hope PC
$NssmExe  = "C:\Tools\nssm\nssm.exe"
$PythonExe = "C:\hope-bridge\.venv\Scripts\python.exe"

& $NssmExe install HopeBridge $PythonExe "-m uvicorn main:app --host 0.0.0.0 --port 7070"
& $NssmExe set HopeBridge AppDirectory "C:\hope-bridge"
& $NssmExe set HopeBridge Start SERVICE_AUTO_START
& $NssmExe set HopeBridge AppStdout "C:\hope-bridge\logs\bridge.log"
& $NssmExe set HopeBridge AppStderr "C:\hope-bridge\logs\bridge-err.log"
Start-Service HopeBridge
```

**NSSM download:** https://nssm.cc/download — extract, copy `win64\nssm.exe` → `C:\Tools\nssm\nssm.exe`

### 6.6 Mock Mode (Critical for Development)

Both the Sage bridge and SynHealth backend support `SAGE_MOCK=1` / `HOPE_MOCK=1`. When mock is on, all bridge routes return static sample data. This lets frontend + backend development proceed without needing the actual Hope software installed.

```python
# In every router:
if settings.HOPE_MOCK:
    return MOCK_PATIENTS[offset:offset+limit]
# else: real ODBC/SDK call
```

---

## 7. Authentication System

Warebot uses JWT access tokens + refresh tokens stored in PostgreSQL.

### 7.1 Token Flow

```
POST /auth/login  →  { access_token (15 min), refresh_token (30 days) }
POST /auth/refresh → new access_token
POST /auth/logout  → revoke refresh_token (delete from DB)
```

### 7.2 Key Decisions

- **HS256 JWT** signed with `JWT_SECRET` (from env, never hardcoded)
- **bcrypt** for password hashing
- **Device keys** — additional per-device HMAC keys for trusted client apps (tablets on wards)
- Roles stored in JWT payload: `["admin", "doctor", "nurse", "receptionist", "pharmacy"]`
- All sensitive endpoints require `Authorization: Bearer <token>` header

### 7.3 For SynHealth — Suggested Roles

```python
ROLES = ["admin", "doctor", "nurse", "pharmacist", "receptionist", "lab_tech", "finance"]
```

---

## 8. Constants / Branding Pattern (Copy This Structure)

All scattered strings are centralized in `src/constants.py`:

```python
# src/constants.py
BOT_NAME = "SynHealth"
BOT_BRAND = "SynHealth Hospital"
EMBEDDING_DIM = 384
MATCH_THRESHOLD = 0.78
DEFAULT_TOP_K = 3

MEDICAL_DISCLAIMER = "..."

# Table names — prefix all with synhealth_
TABLE_PATIENTS   = "synhealth_patients"
TABLE_ADMISSIONS = "synhealth_admissions"
TABLE_LEADS      = "synhealth_leads"
TABLE_USERS      = "synhealth_users"
TABLE_AUDIT_LOGS = "synhealth_audit_logs"
# ...etc

# ENV var keys
ENV_DATABASE_URL   = "DATABASE_URL"
ENV_JWT_SECRET     = "JWT_SECRET"
ENV_HOPE_BRIDGE_URL = "HOPE_BRIDGE_URL"
ENV_HOPE_BRIDGE_KEY = "HOPE_BRIDGE_KEY"
```

**Rule:** Never use a raw string literal for a table name, bot name, or env key anywhere except `constants.py`.

---

## 9. Local Database Client Pattern

Warebot does NOT use the Supabase Python client library in production — it uses a custom `LocalDBClient` that wraps `psycopg2` with a Supabase-compatible query builder interface. This means the same query code works against the local Docker PostgreSQL.

```python
# src/local_db.py — Supabase-compatible interface over psycopg2
db = LocalDBClient(os.getenv("DATABASE_URL"))

# Usage (identical to supabase-py):
result = db.table("synhealth_patients").select("*").eq("status", "admitted").execute()
rows = result.data
```

Copy `local_db.py` verbatim into SynHealth — it handles SELECT, INSERT, UPDATE, UPSERT, RPC calls, pagination, and connection pooling.

---

## 10. Environment Variables Required

Minimum `.env` for SynHealth:

```env
# Core
DATABASE_URL=postgresql://postgres:<password>@db:5432/synhealth
POSTGRES_PASSWORD=<strong_password>
JWT_SECRET=<32+ char random string>

# LLM
DEEPSEEK_API_KEY=<key>
DEEPSEEK_MODEL=deepseek-chat

# Email (lead/alert notifications)
EMAIL_FROM=noreply@synhealth.local
EMAIL_PASS=<app_password>

# Hope Bridge
HOPE_BRIDGE_URL=http://<hope-pc-ip>:7070
HOPE_BRIDGE_KEY=<shared_secret_min_32_chars>
HOPE_BRIDGE_WEBHOOK_SECRET=<another_secret>

# Ops
GRAFANA_PASSWORD=<password>
SAGE_MOCK=0  # rename to HOPE_MOCK=0
DEV_TOKEN_ENABLED=0
```

---

## 11. DRM Hope — First Steps on Site

Before writing integration code, do these on the first hospital visit:

1. **Identify Hope version** — DRM Hope has different editions (Community, Professional). The API/SDK availability varies.
2. **Check database backend** — Most Hope installs use **Microsoft SQL Server** (MSSQL) or **MySQL**. Confirm with `SELECT @@VERSION` via SSMS.
3. **Find ODBC DSN** — Open Windows ODBC Data Source Administrator → System DSNs → note the DSN name and driver.
4. **Export table list** — Run the INFORMATION_SCHEMA query above. Map tables to: patients, wards, admissions, pharmacy, billing, staff, appointments.
5. **Check if Hope has a REST API** — Some newer Hope versions expose HTTP endpoints. If yes, use those instead of ODBC.
6. **Check HL7 FHIR support** — Modern hospital software often supports FHIR R4. If Hope does, use the FHIR API (standard, much cleaner than ODBC).
7. **Note the Hope PC IP** — This is `HOPE_BRIDGE_URL` host. Must be reachable from the Docker server on the LAN.

---

## 12. Quick-Start Checklist for SynHealth

- [ ] Copy `backend/` structure — `app.py`, `src/`, `migrations/`, `scripts/`, `entrypoint.sh`
- [ ] Copy `docker-compose.yml` and `docker-compose.prod.yml` — rename service labels
- [ ] Copy `SynbotUI/` Dockerfile + `nginx.conf` — update proxy routes for new endpoints
- [ ] Copy `src/embed_proxy.py`, `src/local_db.py`, `src/auth_utils.py` verbatim
- [ ] Create `src/constants.py` with SynHealth branding + Hope table names
- [ ] Create `hope-bridge/` (copy `sage-bridge/` structure, adapt for Hope ODBC/API)
- [ ] Copy `sage-bridge/install-service.ps1` → rename to `hope-bridge/install-service.ps1`
- [ ] Copy `.github/workflows/deploy.yml` — update runner label to `synhealth-vm`
- [ ] Write initial migrations (patients, admissions, wards, pharmacy, audit_logs, auth tables)
- [ ] Seed Q&A pairs with hospital domain knowledge (ward FAQs, drug formulary, procedures)
- [ ] Set `HOPE_MOCK=1` during dev; switch to `0` after first site visit and ODBC confirmed working

---

## 13. Kubernetes Strategy (K3s — Same Server, Higher Resilience)

### 13.1 When to Use Docker Compose vs Kubernetes

| Scenario | Use |
|---|---|
| Single VM, low traffic, simple ops | **Docker Compose** (Phase 1 — get live fast) |
| Server has ≥ 8 GB RAM, hospital grows, need zero-downtime deploys | **K3s** (Phase 2 — graduate to K8s) |
| Multi-node cluster (future expansion) | Full K8s |

**Strategy:** Start with Docker Compose to get SynHealth live. Once stable, graduate to K3s on the same machine — no cloud needed. Warebot has full K8s manifests ready in `k8s/`. SynHealth should replicate the same set.

### 13.2 Why K3s (Not Full Kubernetes)

K3s is a CNCF-certified, single-binary Kubernetes distribution (~70 MB). It:
- Runs on a single Ubuntu VM or bare-metal server
- Ships with a local-path storage provisioner (no cloud block storage needed)
- Installs in ~2 minutes with one `curl` command
- Uses the same `kubectl` and manifest files as full K8s
- Is production-grade for single-site LAN deployments

### 13.3 Installation (One Command)

```bash
# On the hospital server — run install-k3s.sh (copy from Warebot k8s/)
chmod +x k8s/install-k3s.sh && ./k8s/install-k3s.sh
```

The script does **5 things automatically**:
1. Installs K3s with Nginx Ingress Controller (Traefik disabled — we use nginx to match the Docker Compose setup)
2. Installs `metrics-server` (required for HPA autoscaling)
3. Builds all 3 Docker images on the VM (`postgres`, `backend`, `frontend`)
4. Imports images into K3s containerd (`docker save | k3s ctr images import`) — K3s has its own runtime, separate from Docker daemon
5. Applies all manifests in order after prompting to fill secrets

### 13.4 Kubernetes Manifest Files (copy `k8s/` from Warebot)

| File | Resource | Purpose |
|---|---|---|
| `00-namespace.yaml` | Namespace | Isolates all resources under `synhealth` namespace |
| `01-secrets.yaml` | Secret | All env secrets (JWT, DB password, bridge key, etc.) — **never commit with real values** |
| `02-configmap.yaml` | ConfigMap | Non-sensitive config (model name, ODBC DSN, mock flags, rate limits) |
| `03-postgres.yaml` | StatefulSet + PVC | PostgreSQL with 20 GB PersistentVolumeClaim — data survives pod restarts |
| `04-migration-job.yaml` | Job | Runs `apply_migrations.py` once before backend starts — prevents race conditions |
| `05-backend.yaml` | Deployment + Service | FastAPI, 2 replicas, rolling update, init container waits for DB |
| `06-backend-hpa.yaml` | HorizontalPodAutoscaler | Auto-scales backend 2–5 pods on CPU >70% or memory >80% |
| `07-frontend.yaml` | Deployment + Service | nginx serving React SPA + reverse proxy |
| `08-ingress.yaml` | Ingress | Nginx Ingress: rate limiting, body size limit, security headers, routes all traffic to frontend |

### 13.5 Critical Design Decisions

**Migration Job (not init container on each pod):**
With 2+ backend replicas, all pods start simultaneously. If migrations ran in each pod's entrypoint, they'd race — causing duplicate-column or constraint errors. The solution: a `batch/v1 Job` runs migrations exactly once before the backend Deployment is created.

```yaml
# 04-migration-job.yaml — key fields
kind: Job
spec:
  backoffLimit: 3          # retry up to 3x if DB not ready yet
  ttlSecondsAfterFinished: 600  # auto-clean pod after 10 min
  template:
    spec:
      restartPolicy: OnFailure
      initContainers:
        - name: wait-for-postgres
          image: busybox:1.36
          command: [sh, -c, "until nc -z db 5432; do sleep 3; done"]
      containers:
        - name: migrate
          command: ["python", "scripts/apply_migrations.py"]  # no uvicorn
```

**Re-run migrations after schema changes:**
```bash
kubectl delete job synhealth-migrate -n synhealth
kubectl apply -f k8s/04-migration-job.yaml
```

**Postgres as StatefulSet (not Deployment):**
StatefulSet gives stable pod identity and ordered restart. The PVC (`ReadWriteOnce`, 20 Gi) is provisioned by K3s's local-path provisioner — no manual storage setup.

**HPA — Horizontal Pod Autoscaler:**
```yaml
# 06-backend-hpa.yaml
minReplicas: 2
maxReplicas: 5
metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
behavior:
  scaleUp:
    stabilizationWindowSeconds: 30    # react fast on spike
    policies:
      - type: Pods
        value: 2
        periodSeconds: 60
  scaleDown:
    stabilizationWindowSeconds: 300   # conservative — don't flap
```

Size `maxReplicas` to server RAM: each backend pod uses ~1.5 GB max. On an 8 GB server, set `maxReplicas: 4`.

**Secrets handling:**
- Non-sensitive config → `ConfigMap` (safe to commit)
- Sensitive values → `Secret` with `stringData` (K8s base64-encodes automatically)
- **Never commit `01-secrets.yaml` with real values** — add it to `.gitignore` after filling in

```yaml
# 01-secrets.yaml pattern
apiVersion: v1
kind: Secret
metadata:
  name: synhealth-secrets
  namespace: synhealth
type: Opaque
stringData:
  POSTGRES_PASSWORD: "<REPLACE>"
  JWT_SECRET: "<REPLACE — python -c 'import secrets; print(secrets.token_hex(64))'>"
  HOPE_BRIDGE_KEY: "<REPLACE>"
  DEEPSEEK_API_KEY: "<REPLACE>"
  ADMIN_PASSWORD: "<REPLACE>"
```

**Ingress — two layers of rate limiting:**
- **Layer 1** (Ingress): `nginx.ingress.kubernetes.io/limit-rps: "1"` + burst 20 — rejects at the cluster edge before pods see the request
- **Layer 2** (nginx.conf inside frontend pod): per-route zones (`api_limit`, `auth_limit`) — finer-grained per-endpoint control

### 13.6 Image Build + Import Workflow (K3s doesn't use Docker daemon)

This is the most common confusion when moving from Docker Compose to K3s:

```bash
# 1. Build with Docker (as normal)
docker build -t synhealth-backend:latest ./backend/
docker build -t synhealth-frontend:latest ./SynbotUI/
docker build -t synhealth-postgres:18 ./backend/db/

# 2. Import into K3s containerd (REQUIRED — K3s ignores Docker images)
docker save synhealth-backend:latest   | sudo k3s ctr images import -
docker save synhealth-frontend:latest  | sudo k3s ctr images import -
docker save synhealth-postgres:18      | sudo k3s ctr images import -

# 3. Set imagePullPolicy: IfNotPresent in all manifests
#    (prevents K3s from trying to pull from Docker Hub)
```

**On every redeploy after code changes:**
```bash
docker build -t synhealth-backend:latest ./backend/
docker save synhealth-backend:latest | sudo k3s ctr images import -
kubectl rollout restart deployment/backend -n synhealth
```

### 13.7 Apply Order (must be sequential)

```bash
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/01-secrets.yaml
kubectl apply -f k8s/02-configmap.yaml
kubectl apply -f k8s/03-postgres.yaml
kubectl wait pod -n synhealth --for=condition=ready -l app=postgres --timeout=120s
kubectl apply -f k8s/04-migration-job.yaml
kubectl wait --for=condition=complete job/synhealth-migrate -n synhealth --timeout=120s
kubectl apply -f k8s/05-backend.yaml
kubectl apply -f k8s/06-backend-hpa.yaml
kubectl apply -f k8s/07-frontend.yaml
kubectl apply -f k8s/08-ingress.yaml
```

### 13.8 Useful kubectl Commands for Day-to-Day Ops

```bash
# See all pods and their status
kubectl get pods -n synhealth

# Tail backend logs
kubectl logs -n synhealth -l app=backend -f

# Check HPA status (current replicas vs desired)
kubectl get hpa -n synhealth

# Check Ingress
kubectl get ingress -n synhealth

# Describe a failing pod (shows events + error)
kubectl describe pod <pod-name> -n synhealth

# Run a one-off command inside the backend pod
kubectl exec -it -n synhealth deployment/backend -- python -c "from src.embed_proxy import get_embedding; print(get_embedding('test'))"

# Force a rolling redeploy (e.g. after importing new image)
kubectl rollout restart deployment/backend -n synhealth
kubectl rollout restart deployment/frontend -n synhealth

# Watch rollout progress
kubectl rollout status deployment/backend -n synhealth
```

### 13.9 Hope Bridge in K8s Context

The Hope Bridge runs on the **Windows PC** (where DRM Hope is installed) — it is **not** containerized or in the K8s cluster. It runs as a NSSM Windows service on the LAN and communicates with the backend over the local network.

In the ConfigMap:
```yaml
HOPE_BRIDGE_URL: "http://192.168.1.<HOPE_PC_IP>:7070"  # LAN IP of the Hope Windows machine
HOPE_MOCK: "1"  # Set to 0 when bridge is confirmed live
```

The K8s backend pod reaches the bridge via this LAN IP — same as Docker Compose. No change to the bridge itself.

### 13.10 Phase Progression Summary

```
Phase 1 (Live fast):   Docker Compose  →  single-command deploy, easy to debug
Phase 2 (Scale):       K3s             →  same server, HPA, zero-downtime rolling deploys
Phase 3 (Multi-site):  Full K8s/cloud  →  if hospital expands to multiple branches
```

For SynHealth, **Phase 1 is the goal** for the first hospital deployment. The K8s manifests in `k8s/` should be built in parallel so the graduation to Phase 2 is a single `install-k3s.sh` run when the hospital is ready.
