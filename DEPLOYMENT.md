# ACE / Placeware — Deployment Walkthrough

> **Current situation:** You are connected to the Windows 10 server via Remote Desktop (RDP) from your dev laptop.
> Everything you do in this guide happens inside that RDP session — on the server — unless a step explicitly says "on your dev laptop."
>
> **Plan:** Deploy ACE first, get it live and verified. Sage Bridge comes after in Part 2.
>
> **Estimated time for Part 1 (ACE app live):** 1.5 – 2 hours.

---

## What Are We Deploying Right Now?

The ACE application — the full Placeware web app. Once this part is done:
- Anyone on the office network goes to `https://SERVER_IP` and uses ACE
- Every future code change you push from your laptop auto-deploys to this server — no manual steps

The Sage Bridge (connecting Sage 50 data) comes in Part 2 after the app is confirmed working.

---

## Glossary

- **WSL2** — Runs a Linux terminal inside Windows 10. Our deploy scripts are Linux-based, so this is required.
- **Docker** — Runs the ACE app in isolated containers. Same behaviour on every machine.
- **GitHub Actions** — Automated pipeline that builds and deploys the app when you push code.
- **Self-hosted runner** — A background service on the server that picks up GitHub Actions jobs and runs them locally.
- **RDP session** — Your Remote Desktop window. Think of it as controlling the server's screen from your laptop.

---

## Progress Map

```
PART 1 (Today):
[ PREP ] → [ WSL2 + Ubuntu ] → [ Docker ] → [ GH Runner ] → [ Push Code ] → [ App Live ]

PART 2 (After app verified):
[ Sage Bridge on Win7 ] → [ Connect to ACE ] → [ Data flowing ]
```

---

## RDP Tips Before You Start

- **Copy-paste into RDP:** Copy text on your laptop → click inside the RDP window → **right-click → Paste** (or Ctrl+V if the session allows it)
- **Open a browser on the server:** Inside the RDP session, open Edge or Chrome — downloads go to the server, not your laptop. This is how you will download Docker Desktop.
- **Open VSCode terminal on the server:** Launch VSCode inside the RDP session → press **Ctrl + `** to open the terminal
- **PowerShell as Administrator:** Inside RDP, click Start → search PowerShell → right-click → **Run as administrator**

---

---

# PART 1 — Get ACE Live

---

## PREP — Before Anything Else

---

### PREP 1 — Generate Your Passwords and Keys

Open a terminal on **your dev laptop** (not in RDP) and run each command below. Copy and save every output value — you will need them in the next step.

**Database password** — make a strong one yourself (no `@` or `$` characters):
```
Example: ACEplaceware2026!
```

**JWT Secret** — run this and copy the output:
```bash
python -c "import secrets; print(secrets.token_hex(64))"
```

**Bridge API Key** — run this and copy the output:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Bridge Webhook Secret** — run it again (different value):
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Keep all four values somewhere safe (a notes app, a secure text file). You are about to paste them into GitHub.

---

### PREP 2 — Add GitHub Secrets

These are the passwords and config values the deployment pipeline reads. They never go into the code.

1. Open GitHub in a browser **on your dev laptop**
2. Go to your repository → click **Settings** (top tab of the repo)
3. Left sidebar → **Secrets and variables** → **Actions**
4. Click **New repository secret** and add each one below

| Secret Name | What to put |
|---|---|
| `DEEPSEEK_API_KEY` | Your DeepSeek API key |
| `DEEPSEEK_MODEL` | `deepseek-chat` |
| `POSTGRES_PASSWORD` | Your database password from PREP 1 |
| `JWT_SECRET` | The 64-char hex from PREP 1 |
| `ADMIN_EMAIL` | The email you want to log into ACE with |
| `ADMIN_PASSWORD` | A strong password for your admin login |
| `EMAIL_FROM` | Gmail address ACE sends notifications from |
| `EMAIL_PASS` | Gmail App Password (Google Account → Security → App Passwords) |
| `SAGE_BRIDGE_URL` | Put `http://localhost:7070` for now — we update this in Part 2 |
| `SAGE_BRIDGE_KEY` | Your Bridge API Key from PREP 1 |
| `SAGE_BRIDGE_WEBHOOK_SECRET` | Your Bridge Webhook Secret from PREP 1 |
| `GRAFANA_PASSWORD` | Any password for the monitoring dashboard |

> You should have exactly **12 secrets** when done. If any are missing the pipeline will fail immediately.

---

### PREP 3 — Commit the Pending Code Changes

On your **dev laptop**, open a terminal in the project folder and run:

```bash
git add SynbotUI/nginx.conf
git add backend/src/routers/controls.py
git add backend/src/routers/sage_csv_import.py
git commit -m "fix: nginx controls proxy, remove stub routes, fix Sage CSV header parsing"
```

You should see:
```
[main abc1234] fix: nginx controls proxy...
 3 files changed...
```

> **Do NOT run `git push` yet.** Pushing triggers the deployment. The server needs to be set up first or the pipeline will fail with no runner to pick it up. You will push at Step 7.

---

---

## ON THE SERVER (inside your RDP session)

> Everything from here until Step 7 happens **inside the RDP window** — you are working on the Windows 10 server.

---

### Step 1 — Check What Is Already Installed

Open PowerShell as Administrator inside the RDP session and run these checks. This tells us what we can skip.

**Check if WSL2 is already there:**
```powershell
wsl --status
```
- Shows `Default Version: 2` → WSL2 is enabled. ✅ You can skip Step 2A.
- Shows error or nothing → WSL2 needs to be enabled. Do Step 2A.

**Check if Ubuntu is already installed:**
```powershell
wsl -l -v
```
- Shows `Ubuntu-22.04` with `VERSION 2` → Ubuntu is ready. ✅ You can skip Step 2B.
- Shows nothing or wrong version → Do Step 2B.

**Check if Docker is installed:**
```powershell
docker --version
```
- Shows a version number → Docker CLI exists. Still check Docker Desktop is running (Step 3).
- Shows "not recognized" → Do Step 3 in full.

---

### Step 2A — Enable WSL2 (skip if already enabled)

In **PowerShell as Administrator**:

```powershell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
```

**Restart the server.** After restart, reconnect via RDP, open PowerShell as Administrator again and run:

```powershell
wsl --set-default-version 2
```

---

### Step 2B — Install Ubuntu (skip if already installed)

You have two options depending on what file you have ready:

**Option A — You have the Ubuntu `.AppxBundle` file (e.g. on a USB drive):**
```powershell
Add-AppxPackage -Path "D:\Ubuntu_2204.AppxBundle"
```
Replace `D:\` with wherever the file is. When done, open Ubuntu from Start menu to finish setup (create username + password).

**Option B — Download directly (if internet is available on the server):**
```powershell
wsl --install -d Ubuntu-22.04
```
Restart when prompted, then reconnect via RDP.

**After Ubuntu is installed and open for the first time:**
- Create a username when prompted (e.g. `ace`) — keep it simple, lowercase
- Create a password — the cursor will not move while you type, this is normal
- Confirm the password

> Write down the Ubuntu username and password. You need the password every time you run `sudo`.

**Enable systemd** (do this inside the Ubuntu terminal):
```bash
sudo tee /etc/wsl.conf <<EOF
[boot]
systemd=true
EOF
```

Then in PowerShell:
```powershell
wsl --shutdown
```

Reopen Ubuntu from the Start menu — systemd is now active.

---

### Step 3 — Install Docker Desktop

Inside the RDP session, open **Edge or Chrome** on the server and go to:
```
https://docker.com/products/docker-desktop
```

Click **Download for Windows — AMD64** (standard Windows 10 PC processor).

Run the downloaded installer:
- ✅ Keep **"Use WSL2 based engine"** checked
- Complete the install
- When Docker Desktop opens, skip the tutorial

**Connect Docker to Ubuntu:**
1. Click the ⚙️ gear icon in Docker Desktop
2. Click **Resources** → **WSL Integration**
3. Toggle on **Ubuntu-22.04**
4. Click **Apply & Restart**

**Verify it works** — open the Ubuntu terminal and run:
```bash
docker ps
```

Expected (empty table, no error):
```
CONTAINER ID   IMAGE   COMMAND   CREATED   STATUS   PORTS   NAMES
```

If you see **"permission denied"**:
```bash
sudo usermod -aG docker $USER
```
Close and reopen the Ubuntu terminal, then run `docker ps` again.

---

### Step 4 — Install the GitHub Actions Runner

The runner is the background service that watches GitHub for new code pushes and runs the deployment on this server.

**Get your unique setup link from GitHub:**
1. Go to your GitHub repo in a browser (on your dev laptop or inside RDP — either works)
2. Click **Settings** → left sidebar → **Actions** → **Runners**
3. Click **New self-hosted runner**
4. Select **Linux** and **x64**
5. Leave this page open — you will copy commands from it

**In the Ubuntu terminal on the server:**

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner
```

Now copy the **`curl` download command** shown on the GitHub page and paste it here. It looks like:
```bash
curl -o actions-runner-linux-x64.tar.gz -L https://github.com/actions/runner/releases/download/v2.x.x/actions-runner-linux-x64-2.x.x.tar.gz
```

Then run:
```bash
tar xzf ./actions-runner-linux-x64-*.tar.gz
```

Now copy the **`./config.sh` command** from the GitHub page and paste it. It includes a unique token that is valid for 1 hour:
```bash
./config.sh --url https://github.com/YOUR_ORG/YOUR_REPO --token YOUR_TOKEN
```

Press **Enter** for all prompts. Or type `placeware-win10` when asked for the runner name.

**Install as a permanent service** (survives reboots):
```bash
sudo ./svc.sh install
sudo ./svc.sh start
```

**Confirm it is running:**
```bash
sudo ./svc.sh status
```
Look for `active (running)` in green.

**Confirm on GitHub:** Go to repo → Settings → Actions → Runners. Your runner should appear with a green dot and status **Idle**. If it shows Idle → the runner is ready to receive jobs.

> **If it shows Offline:** Run `sudo ./svc.sh start` in the Ubuntu terminal and refresh the GitHub page.

---

### Step 5 — Open the Firewall Ports

Team members connect to ACE on port 443. We need to tell Windows Firewall to allow it.

In **PowerShell as Administrator** (inside RDP):

```powershell
netsh advfirewall firewall add rule name="Placeware HTTPS" dir=in action=allow protocol=TCP localport=443
```
Should print: `Ok.`

```powershell
netsh advfirewall firewall add rule name="Placeware HTTP" dir=in action=allow protocol=TCP localport=80
```
Should print: `Ok.`

---

### Step 6 — Confirm the Server's LAN IP

You need the IP address that other office machines use to reach this server.

In the Ubuntu terminal, run:
```bash
ip addr show | grep "inet " | grep -v "127.0.0.1"
```

You will see several lines. You want the one on your **physical network card** (usually `eth0` or `ens` something), not Docker's virtual networks. Example output:
```
inet 192.168.0.112/20  ...  eth0          ← this is your real LAN IP
inet 172.17.0.1/16      ...  docker0       ← ignore this, Docker virtual
inet 172.19.0.1/16      ...  docker_gwbridge ← ignore this, Docker virtual
```

> **Note:** `172.16.x.x` through `172.31.x.x` are all valid private/LAN addresses — not just `192.168.x.x`. If your network uses `172.18.x.x` that is perfectly fine.

To confirm which IP is correct, run this from **your dev laptop** (outside RDP):
```powershell
ping 192.168.0.112
```
If you get replies → that is the right IP. If it times out → try the other IP from the list.

**Write down the confirmed IP.** This is your app URL: `https://192.168.0.112`

---

### Step 7 — Clone the Repo on the Server

> **Why we need this:** The GitHub Actions runner clones a fresh copy of the repo every time it runs a deployment job. But we also need a permanent copy on the server so the deploy scripts (`start-stack.sh`, `watchdog.sh`) are always accessible even outside of a pipeline run.

In the **Ubuntu terminal**, clone the repo into the home directory:

```bash
cd ~
git clone https://github.com/YOUR_ORG/YOUR_REPO.git placeware
```

Replace `YOUR_ORG/YOUR_REPO` with your actual GitHub repository path. Example:
```bash
git clone https://github.com/MofeAkinolaPSE/placeware-x1.git placeware
```

If the repo is **private** (which it likely is), GitHub will ask for credentials. Use a Personal Access Token (not your password):
1. Go to GitHub → click your profile photo → **Settings**
2. Left sidebar → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
3. Click **Generate new token** → give it a name → check the **repo** scope → Generate
4. Copy the token — paste it as the password when git asks

After cloning you should see:
```
Cloning into 'placeware'...
remote: Counting objects: ...
Resolving deltas: done.
```

Verify it worked:
```bash
ls ~/placeware
```
You should see folders like `backend`, `SynbotUI`, `deploy`, `sage-bridge`.

---

### Step 8 — Create the `.env` File

> **What is `.env`?** It is a plain text file containing all the app's passwords and settings. The app reads it on startup. The deployment pipeline creates this file automatically from your GitHub Secrets every time it runs — **you do not need to fill it in manually.** However, for the very first run we create it manually so the pipeline has something to work with if it needs to reference the file during bootstrap.

In the Ubuntu terminal:
```bash
cd ~/placeware/backend
cp .env.example .env
```

Now open it to fill in the real values:
```bash
nano .env
```

This opens a simple text editor inside the terminal. Use arrow keys to navigate. Find each line below and replace the placeholder with your real value:

```
POSTGRES_PASSWORD=         ← paste your DB password here
JWT_SECRET=                ← paste your 64-char JWT secret here
ADMIN_EMAIL=               ← your admin login email
ADMIN_PASSWORD=            ← your admin password
DEEPSEEK_API_KEY=          ← your DeepSeek API key
DEEPSEEK_MODEL=deepseek-chat
EMAIL_FROM=                ← your Gmail address
EMAIL_PASS=                ← your Gmail App Password
SAGE_MOCK=1                ← keep as 1 for now (skips Sage bridge until Part 2)
```

Leave everything else as-is for now.

**Save and exit nano:**
- Press **Ctrl + O** → press **Enter** to confirm the filename
- Press **Ctrl + X** to exit

Verify it saved:
```bash
grep "POSTGRES_PASSWORD" .env
```
Should show your actual password, not a placeholder.

---

## DEPLOY — First Deployment via Docker Compose

> We use `docker compose` directly for the first deployment. It is simpler and works perfectly
> on Docker Desktop + WSL2. The `start-stack.sh` script is designed for bare Linux servers
> and tries to configure SSH/UFW/fail2ban — none of which apply here. Skip it.

---

### Step 9 — Build and Start the App

In the **Ubuntu terminal**, navigate to the backend folder and bring everything up:

```bash
cd ~/Placewaresynbot/backend
docker compose up -d --build
```

- `--build` — builds the Docker images fresh (required on first run)
- `-d` — runs all containers in the background so you get your terminal back

**What you will see:** Docker downloading base images then building layer by layer.
This takes **5–8 minutes** on first run. A lot of text is normal — only red `ERROR` lines are a problem.

**Watch the build progress live (optional — open a second terminal tab):**
```bash
docker compose logs -f
```
Press **Ctrl+C** to stop watching. The containers keep running.

**When the build finishes, confirm everything is up:**
```bash
docker compose ps
```

Expected — all containers showing `Up` or `healthy`:
```
NAME                    STATUS
backend-db-1            Up (healthy)
chat-backend.v1         Up (healthy)
placeware-frontend.v1   Up (healthy)
```

If any container shows `Exit` or `Restarting`, run:
```bash
docker compose logs backend
```
Paste the last 20 lines here and we will fix it.

---

### Step 9b — Seed the Admin User

After the containers are healthy, create the admin account so you can log in:

```bash
docker compose exec backend python seed_admin.py
```

Expected output:
```
Admin user created: your@email.com
```

If it says "Admin already exists" — that is fine, the account is already there.

---

### Step 10 — Open the App and Verify It Works

From any browser on the office network, go to:
```
https://192.168.0.112
```
(Use the confirmed LAN IP from Step 6)

**You will see a security warning** — "Your connection is not private." This is expected. The app uses a self-signed certificate on the local network.

- Chrome: **Advanced → Proceed to site**
- Firefox: **Advanced → Accept the Risk and Continue**
- Edge: **Advanced → Continue to site**

You only do this once per browser. After that it remembers.

**Log in** with the `ADMIN_EMAIL` and `ADMIN_PASSWORD` you added to GitHub Secrets.

**Checklist — confirm each one works:**
- [ ] Login page loaded
- [ ] Logged in successfully → landed on Dashboard
- [ ] Left sidebar navigation is visible
- [ ] Operations → Project Controls → no error, page loads
- [ ] Sage Import page is accessible

**If all boxes are checked — the ACE app is live.** 

---

### Step 10b — Load the Processed Sage Data (One-Time Import)

> **What this is:** The full Sage 50 dataset — 1.11M rows across 18 tables — already cleaned and
> processed on the dev machine: de-duplicated PO/AP invoices, real AR due dates, customer
> attribution repair, credit limits, item costs + expiry dates, customer profitability, and the
> enriched CRM customer master. Loading this dump means the client's ACE starts with the exact
> same data as the verified dev build — no need to re-run the XLSX ingestion pipeline on the server.

**The two files you need** (both live in the repo under `data-assimilation/dumps/`):

| File | Purpose |
|---|---|
| `ace_sage_data_dump_2026-07-07.sql.gz` (~15 MB) | The data itself (plain SQL, gzipped) |
| `ace_sage_data_restore_prep.sql` | Clears the target tables first — makes the load safe to re-run |

**Prerequisite — the app must be on the latest code (Step 9 already did this).** The dump is
data-only; the tables and views it fills are created by migrations `093`–`096`, which run
automatically when the backend container starts. If the code on the server is older than
2026-07-07, `git pull` and redeploy first, or the load will fail with "table does not exist."

**1. Get the dump onto the server.** If the `data-assimilation/dumps/` folder is committed to the
repo, it is already there from Step 7 — skip ahead. Otherwise copy it from your dev laptop via the
RDP session (copy the two files → paste into a folder inside the RDP window, e.g. `C:\temp\`).
Files on `C:\temp` are visible in Ubuntu at `/mnt/c/temp/`.

**2. Load the data.** In the **Ubuntu terminal** (adjust the path if you copied via `C:\temp`):

```bash
cd ~/placeware/data-assimilation/dumps    # or: cd /mnt/c/temp

# 2a. Clear the target tables (idempotent — safe to re-run any time)
docker exec -i backend-db-1 psql -U postgres -d synbot_demo < ace_sage_data_restore_prep.sql

# 2b. Load the dump (~1–3 minutes for the 915K GL rows)
gunzip -c ace_sage_data_dump_2026-07-07.sql.gz | docker exec -i backend-db-1 psql -U postgres -d synbot_demo
```

Expected: a stream of `TRUNCATE TABLE` / `SET` / `COPY` lines with **no `ERROR` lines**.
If 2b fails midway (e.g. connection drop), just re-run 2a then 2b.

> **Note:** the prep script truncates `customers` with CASCADE (it is referenced by
> `crm_activities`). On a fresh server those tables are empty, so nothing of value is lost.

**3. Restart the backend to clear its caches** (KPIs cache for up to 10 minutes):

```bash
cd ~/placeware/backend
docker compose restart backend
```

**4. Verify the data landed.** Run the spot-check — the numbers should match exactly:

```bash
docker exec backend-db-1 psql -U postgres -d synbot_demo -c "
SELECT
 (SELECT COUNT(*) FROM sage_gl_detail_snapshot)                      AS gl_detail,
 (SELECT COUNT(*) FROM sage_ar_snapshot)                             AS ar_rows,
 (SELECT COUNT(*) FROM sage_ar_snapshot WHERE due_date IS NOT NULL)  AS ar_with_due,
 (SELECT COUNT(*) FROM sage_purchase_orders_snapshot)                AS pos,
 (SELECT COUNT(*) FROM customers)                                    AS customers,
 (SELECT COUNT(*) FROM customers WHERE credit_limit > 0)             AS w_credit_limit;
"
```

Expected:
```
 gl_detail | ar_rows | ar_with_due | pos  | customers | w_credit_limit
-----------+---------+-------------+------+-----------+----------------
    914992 |  101086 |       33725 | 1180 |      1538 |           1093
```

**5. Verify in the browser** — log into ACE and check:
- [ ] Dashboard KPI cards non-zero (AR ≈ ₦18.06B, AP ≈ ₦6.95B, Cash ≈ ₦336.6M)
- [ ] Executive Summary → AR Aging pie chart renders four buckets
- [ ] Finance → AR & Alerts → Credit Risk tab shows ~1,008 scored customers
- [ ] Operations → Purchase Orders → 1,180 total / ~1,175 overdue
- [ ] Operations → Inventory → 791 SKUs, ~40 items with stock, expiry dates visible
- [ ] CRM → Customer Accounts → 1,538 customers with city/terms/credit limits;
      the 360 view (eye icon) shows receivables, profitability, and top items

**All checked = the client instance now runs on the full processed dataset.**

> **Regenerating the dump later** (after new data work on the dev machine) — run on the dev laptop:
> ```powershell
> docker exec backend-db-1 sh -c "pg_dump -U postgres -d synbot_demo --data-only --no-owner --no-privileges -t sage_coa_snapshot -t sage_vendors_snapshot -t sage_customers_snapshot -t sage_items_snapshot -t sage_inventory_snapshot -t sage_purchase_orders_snapshot -t sage_ar_snapshot -t sage_ap_snapshot -t sage_invoice_lines_snapshot -t sage_inv_transactions_snapshot -t sage_gl_snapshot -t sage_gl_detail_snapshot -t sage_cash_register_snapshot -t sage_gl_account_summary_snapshot -t sage_customer_sales_snapshot -t customers -t reconciliation_tracking -t placeware_inventory_events | gzip > /tmp/ace_sage_data_dump.sql.gz"
> docker cp backend-db-1:/tmp/ace_sage_data_dump.sql.gz "data-assimilation\dumps\ace_sage_data_dump_NEW-DATE.sql.gz"
> ```
> Then repeat this step on the server with the new filename.

---

### Step 11 — Install the Watchdog (Auto-Recovery Service)

The watchdog checks the app containers every 60 seconds and restarts anything that goes unhealthy.

In the **Ubuntu terminal** (inside RDP):

```bash
REPO_PATH=$(find ~/actions-runner/_work -name "watchdog.sh" 2>/dev/null | head -1)
sudo cp "$REPO_PATH" /usr/local/bin/placeware-watchdog.sh
sudo chmod +x /usr/local/bin/placeware-watchdog.sh
```

```bash
sudo tee /etc/systemd/system/placeware-watchdog.service <<'EOF'
[Unit]
Description=Placeware Stack Watchdog
After=docker.service
[Service]
ExecStart=/usr/local/bin/placeware-watchdog.sh
Restart=always
RestartSec=30
[Install]
WantedBy=multi-user.target
EOF
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now placeware-watchdog
sudo systemctl status placeware-watchdog
```

Look for `active (running)` in green. Press **Q** to exit.

---

### Step 12 — Test the CI/CD Pipeline (Auto-Redeploy)

This confirms that future code pushes update the server automatically.

On your **dev laptop**, make any tiny change (add a blank line to any file) and push:

```bash
git add .
git commit -m "test: verify CI/CD auto-redeploy"
git push origin main
```

1. Keep the ACE app open in a browser
2. GitHub Actions → a new job starts within seconds
3. The app stays **fully usable** while the deploy runs (~3–5 min)
4. After the job succeeds → hard-refresh the browser (**Ctrl+Shift+R**)

Auto-redeploy confirmed = Part 1 complete.

---

### Step 13 — Give Team Members Access

Share this with your team:

```
URL:           https://192.168.0.112    ← use the actual LAN IP from Step 6
First visit:   Accept the security warning → Advanced → Proceed  (once only)
Username:      Their work email
Password:      Set by admin
```

To create accounts: log into ACE as admin → **Settings → Users → Invite**

---

---

# PART 2 — Sage Bridge (Do After App Is Verified)

> Come back to this section once the ACE app is confirmed working and team members can log in.
> The Sage Bridge connects Sage 50 data (invoices, inventory, customers) into ACE.
> This runs on the **Windows 7 machine** where Sage 50 is installed — not the Windows 10 server.

Steps for Part 2 are tracked separately. In summary:
1. Install Python 3.8 + .NET Framework 4.7 on the Windows 7 machine
2. Copy the `sage-bridge` folder to `C:\placeware\sage-bridge\`
3. Create the Pervasive ODBC data source (points to the Sage company folder)
4. Configure `sage-bridge/.env` with the Sage paths and ACE server IP
5. Install NSSM and run `.\install-service.ps1` to make it a Windows Service
6. Open port 7070 in Windows 7 firewall
7. Update the `SAGE_BRIDGE_URL` GitHub Secret to `http://WIN7_IP:7070`
8. Push a small change to `main` → ACE redeploys and picks up the real bridge URL

---

---

# TROUBLESHOOTING

### App Issues (Windows 10 server)

| Problem | Fix |
|---|---|
| GitHub runner shows Offline on GitHub | Ubuntu terminal: `cd ~/actions-runner && sudo ./svc.sh start` |
| `docker ps` gives permission denied | `sudo usermod -aG docker $USER` → close and reopen Ubuntu terminal |
| Pipeline fails at "local registry" | `docker run -d -p 5000:5000 --restart=always --name registry registry:2` |
| Login fails after deploy | `docker exec $(docker ps -qf name=backend) python seed_admin.py` |
| Data load fails: "table does not exist" | Backend code is older than the dump — `git pull` + redeploy (migrations 093–096 must run), then retry Step 10b |
| Dashboards still zero after data load | Caches — `docker compose restart backend`, then hard-refresh the browser (Ctrl+Shift+R) |
| App unreachable from other machines | Rerun the `netsh` firewall commands from Step 5 |
| Containers keep restarting | `docker service logs placeware_backend --tail 50` — read the error |

### Useful Commands (Ubuntu terminal on the server)

```bash
# See all running services
docker service ls

# Read backend logs live (Ctrl+C to stop)
docker service logs placeware_backend --tail 50 -f

# Force restart backend without redeploying
docker service update --force placeware_backend

# Check watchdog
sudo systemctl status placeware-watchdog

# Get LAN IP
hostname -I
```
