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

### Step 10b — Replace the Server's Database with the Latest Dump

**What you are doing:** replacing the server's old data with the up-to-date copy from the dev
laptop, and bringing the server's code up to date so it understands that copy.

**At a glance**

| | |
|---|---|
| Time needed | About 30 minutes. The app is offline for about 10 of them, so pick a quiet time. |
| What changes | The server's data is replaced. Anything typed into the server since the last load is overwritten. Step 3 saves a copy first, so you can always go back. |
| After the load | Log in with the **dev laptop's** usernames and passwords. The dump carries the dev laptop's user accounts. |
| Where you type | Step A on the **dev laptop**. Everything after that on the **server**, in the Ubuntu terminal. |

**The file** (on the dev laptop, inside the project folder):

| File | Size | Fingerprint (SHA-256) |
|---|---|---|
| `data-assimilation\dumps\ace_full_dump_2026-10-09.sql.gz` | 39.4 MB | `476431882780edbefc77b480c2e7b464fb9235bba5f5fa0c246d005c303fb96f` |

It holds:

- Sage history up to 7 Oct 2026, and ACE Books from 8 Oct.
- Next invoice number 53543.
- Every ACE Books change up to 9 Oct: recalls, returns, history on every list, receipts and payments from the document, adding items to invoices, and correcting receipts and vouchers.

Use this file only. The older `ace_full_dump_2026-10-07.sql.gz` and `ace_sage_data_dump_*.sql.gz` files are out of date.

**Tick these off as you go**

- [ ] A. Code pushed from the dev laptop
- [ ] 1. Server code updated and rebuilt
- [ ] 2. Dump copied to the server and fingerprint checked
- [ ] 3. Server's current data saved (your undo button)
- [ ] 4. App stopped
- [ ] 5. Old database replaced with an empty one
- [ ] 6. New data loaded
- [ ] 7. App started
- [ ] 8. Numbers checked
- [ ] 9. Test data removed
- [ ] 10. Checked in the browser
- [ ] 11. Tidied up

---

#### How to run the commands

- On the **server**, open the Ubuntu terminal: in the RDP session, open the Start menu, type **Ubuntu** and open it. The prompt looks like `ace@PLACEWARE-AI-SERV:~$`.
- Copy **one grey box at a time**, paste it with **right-click** (or Ctrl+Shift+V) and press **Enter**.
- Wait for the prompt to come back. Then compare what you see with **"You should see"** before moving on.
- Lines starting with `#` are notes. Pasting them is harmless.

---

**Step A — On the dev laptop: send the latest code to GitHub.**

The new data needs the new code, which adds tables (migrations up to 139). In **PowerShell** in the project folder:

```powershell
git add -A
git reset -q -- "tsc*.out"
git commit -m "ACE Books 9 Oct: recalls, returns, history lists, corrections, security headers"
git push
```

(The second line leaves out scratch type-check files. Dumps, backups and `.env` files are never
committed: `.gitignore` excludes them.)

You should see: the push finish with a line like `main -> main`.

> Already pushed everything? Skip this step.

---

**Step 1 — On the server: get the new code and rebuild.**

```bash
cd ~/Placewaresynbot && git pull
cd ~/Placewaresynbot/backend
docker compose build backend frontend
docker compose up -d
```

You should see: the build finish (5–10 minutes), then lines ending in `Started` or `Running`.

- `git pull` says **"Already up to date"** but Step A pushed new code: the server is looking at another branch. Ask for help before going on.

---

**Step 2 — Copy the dump to the server and check it.**

1. On the dev laptop, copy `ace_full_dump_2026-10-09.sql.gz` (right-click › Copy).
2. In the RDP window, open **File Explorer** on the server and go to **`C:\temp`**. Create the folder if it doesn't exist. Paste the file there.
3. In the Ubuntu terminal:

```bash
cp /mnt/c/temp/ace_full_dump_2026-10-09.sql.gz ~/
sha256sum ~/ace_full_dump_2026-10-09.sql.gz
```

You should see this, followed by the file name:

```
476431882780edbefc77b480c2e7b464fb9235bba5f5fa0c246d005c303fb96f
```

**It must match exactly.**

- **Different fingerprint:** the copy was damaged. Copy the file again.
- **"No such file or directory":** the file isn't in `C:\temp`. Check where you pasted it.

---

**Step 3 — Save a copy of the server's current data** (your undo button).

```bash
mkdir -p ~/db-backups
docker exec backend-db-1 pg_dump -U postgres -d synbot_demo --no-owner --no-acl | gzip > ~/db-backups/server-before-restore.sql.gz
ls -lh ~/db-backups/
```

You should see: `server-before-restore.sql.gz` with a size in **MB**, for example `38M`.

- **The size is only a few K:** stop here and ask for help. The copy didn't work.

---

**Step 4 — Stop the app**, so nobody changes data while it is being replaced. The database keeps running.

```bash
cd ~/Placewaresynbot/backend
docker compose stop backend frontend
```

You should see: `Stopped` for the backend and the frontend. The website is now offline.

---

**Step 5 — Delete the old database and create an empty one.**

```bash
docker exec backend-db-1 psql -U postgres -c "DROP DATABASE synbot_demo WITH (FORCE);"
docker exec backend-db-1 psql -U postgres -c "CREATE DATABASE synbot_demo;"
```

You should see: `DROP DATABASE`, then `CREATE DATABASE`.

---

**Step 6 — Load the new data.** This takes 2–5 minutes, and the terminal stays quiet while it works.

```bash
gunzip -c ~/ace_full_dump_2026-10-09.sql.gz | docker exec -i backend-db-1 psql -q -v ON_ERROR_STOP=1 -U postgres -d synbot_demo
echo "exit code: $?"
```

You should see: `exit code: 0`. A few `set_config` or blank lines before it are normal.

- **An ERROR line, or an exit code other than 0:** run Step 5 again, then Step 6 again.
- **It fails a second time:** put the old data back (Step 5, then the box below) and ask for help.

```bash
gunzip -c ~/db-backups/server-before-restore.sql.gz | docker exec -i backend-db-1 psql -q -U postgres -d synbot_demo
```

---

**Step 7 — Start the app again.**

```bash
docker compose up -d
docker compose logs -f backend
```

You should see: the log scroll by and stop at `Application startup complete`. The migration lines say `Skipping already-applied`.

Press **Ctrl+C** to stop watching the log. The app keeps running.

---

**Step 8 — Check the data loaded correctly.**

```bash
docker exec backend-db-1 psql -U postgres -d synbot_demo -c "
SELECT
 (SELECT history_until FROM fin_settings LIMIT 1)                                     AS history_until,
 (SELECT COUNT(*) FROM fin_sage_gl_lines)                                             AS sage_gl_lines,
 (SELECT COUNT(*) FROM fin_sales_invoices WHERE status <> 'VOID')                     AS invoices,
 (SELECT COUNT(*) FROM customers)                                                     AS customers,
 (SELECT COUNT(*) FROM fin_data_exceptions WHERE status = 'OPEN')                     AS open_data_issues,
 (SELECT next_value FROM fin_number_sequences WHERE doc_type='SALES_INVOICE' LIMIT 1) AS next_invoice,
 (SELECT COUNT(*) FROM schema_migrations)                                             AS migrations;"
```

You should see exactly these numbers:

```
 history_until | sage_gl_lines | invoices | customers | open_data_issues | next_invoice | migrations
---------------+---------------+----------+-----------+------------------+--------------+------------
 2026-10-07    |        409156 |     1134 |      1545 |               17 |        53543 |        132
```

---

**Step 9 — Remove the August test data** from the Operations Queue: test deliveries, test riders and two test recalls. The script saves a backup first.

```bash
cd ~/Placewaresynbot/backend
bash scripts/cleanup_test_logistics.sh
```

You should see: a `Backup:` line, then a small table showing `deliveries_left 0`, `routes_left 0` and `recall_cases_left 0`, then `Done.`

---

**Step 10 — Check in the browser.** Open ACE and log in with the **dev laptop's** username and password.

- [ ] **Dashboard:** the Operations Queue no longer lists test deliveries.
- [ ] **ACE Books › Finance Control Tower:** a yellow "data issues need a decision" banner.
- [ ] **ACE Books › Invoice Register** (in the sidebar): opens the register. **New invoice** says **No. 53543**.
- [ ] **ACE Books › Sales & Receivables › Receipts:** thousands of receipts, tagged **Sage**.
- [ ] **ACE Books › Purchases & Payables › Returns / debit notes:** totals at the top. "Credit brought from Sage" shows ₦27,957,713.53.
- [ ] **ACE Books › Stock › Stock counts:** a table of every item and batch in stock.
- [ ] **Close & Controls › Data issues:** 17 open issues.
- [ ] **Settings › Data Backup:** click **Back up now**, then **Save to this computer**. This proves backups work on the server.

All ticked = done.

---

**Step 11 — Tidy up.** The dump holds every client and financial record, so don't leave copies lying around.

```bash
rm ~/ace_full_dump_2026-10-09.sql.gz
```

- Delete the file from `C:\temp` too (File Explorer › right-click › Delete).
- Keep `~/db-backups/` for a week in case anything looks wrong. Then remove it with `rm -r ~/db-backups`.

---

**If something goes wrong**

| What you see | What to do |
|---|---|
| `relation ... does not exist` / `table does not exist` | The server's code is older than the dump. Do Step A and Step 1, then repeat from Step 5. |
| The website shows **502 Bad Gateway** after Step 7 | Wait one minute and refresh. Still there? Run `docker compose restart frontend`. |
| You can't log in | Use the **dev laptop's** username and password, not the server's old one. |
| Numbers in Step 8 differ | Stop and ask for help. Don't let staff use it yet. |
| You want the old data back | Step 5, then the "put the old data back" box in Step 6, then Step 7. |

> **For the developer — making the next dump** (on the dev laptop, PowerShell in the project folder):
> ```powershell
> docker exec backend-db-1 sh -c "pg_dump -U postgres -d synbot_demo --no-owner --no-acl --exclude-table-data=license_state --exclude-table-data=system_backups | gzip -9 > /tmp/ace_full_dump.sql.gz"
> docker cp backend-db-1:/tmp/ace_full_dump.sql.gz "data-assimilation\dumps\ace_full_dump_NEW-DATE.sql.gz"
> docker exec backend-db-1 rm /tmp/ace_full_dump.sql.gz
> Get-FileHash "data-assimilation\dumps\ace_full_dump_NEW-DATE.sql.gz" -Algorithm SHA256
> ```
> Then update the file name, size, fingerprint and expected numbers in this step.

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

# LOCAL SAME-MACHINE SAGE BRIDGE TEST

> **When to use this section:** you have Sage 50 installed on the **same PC** as your ACE dev environment (not the two-machine VM + Windows-7 setup in Part 2 below), and you want to prove the whole pipeline works — Sage 50 → Bridge → ACE — before anything goes near a real deployment. This is a different scenario from Part 2, so it gets its own walkthrough.
>
> **Glossary for this section:**
> - **DSN** — "Data Source Name." A saved connection profile Windows uses to let a program talk to a database. The bridge uses one to read Sage's data.
> - **Outbox** — a small local queue the bridge keeps. When it detects a new invoice, it drops an event here first, then tries to deliver it to ACE, retrying automatically if ACE is briefly unreachable.
> - **`host.docker.internal`** — a special address Docker Desktop provides automatically. From inside a container, it always means "the Windows PC this container is running on." You don't configure it; it just works.
> - **Webhook** — a URL the bridge calls (like a phone number it dials) whenever something changes in Sage, so ACE finds out immediately instead of having to constantly ask.

---

## Why `python main.py` Just Failed (Two Different Errors, Two Different Fixes)

**Error 1 — the first one you hit:**
```
ValidationError: BRIDGE_API_KEY is unset or still a placeholder
```
This means the bridge refuses to start, on purpose. `sage-bridge/config.py` keeps a list of known placeholder values, and `placeware-bridge-dev-key-2026` (the value currently sitting in `sage-bridge/.env`) is literally on that list. It's the same key used as a password every time ACE talks to the bridge, so a shared, guessable value would be a real security hole in production. **Phase A** below fixes it.

**Error 2 — after fixing Error 1, you'll likely hit this next** (both DLL load and ODBC connection failing the same way):
```
Failed to load Sage SDK DLL ... An attempt was made to load a program with an incorrect format.
ODBC connection failed: ('IM014', ... 'The specified DSN contains an architecture mismatch between the Driver and Application')
```
This is a **32-bit vs 64-bit mismatch**. Sage 50 2013's database driver and SDK are both 32-bit only — a 64-bit Python interpreter physically cannot load them, no matter how correct your `.env` values are. If your terminal prompt shows `(.venv)` when you're inside `sage-bridge\`, check where that venv actually lives first — it's easy to still have a *different* project's 64-bit venv active from earlier work. **Phase 0** below fixes it.

> **Why this matters even though your teammate already got Sage's DSN and company path working:** those are two separate things. The DSN being *created correctly* (in the 32-bit ODBC admin tool) doesn't help if the *program connecting to it* is 64-bit — that's exactly what "architecture mismatch" means: driver and caller disagree on bitness. Phase 0 fixes the caller's side.

---

## PHASE 0 — Set Up the Bridge's Own 32-bit Python Environment

**Why this matters:** the bridge needs its *own* virtual environment built on 32-bit Python 3.9.13 — it cannot share ACE's backend venv (which is 64-bit, built for a completely different purpose). Running the bridge under the wrong interpreter is what produced both DLL-load and ODBC errors above.

**0.1 — Check what's currently active.** In your PowerShell window:
```powershell
python -c "import struct, sys; print(struct.calcsize('P')*8, sys.executable)"
```
If this prints `64` and a path containing `backend\.venv`, that confirms it — you're running the bridge under the backend's environment. Close this terminal and open a fresh PowerShell window (so no old venv activation carries over).

**0.2 — Check whether 32-bit Python 3.9.13 is already installed.** Some machines have it side-by-side with 64-bit Python already, from a previous setup attempt:
```powershell
py -3.9-32 -c "import struct; print(struct.calcsize('P')*8)"
```
If this prints `32`, skip to **0.4** — you already have it, you just need a venv built from it. If you get an error like "no suitable Python runtime found," continue to 0.3.

**0.3 — Install 32-bit Python 3.9.13.** Go to the official release page: `https://www.python.org/downloads/release/python-3913/`. Scroll to the **Files** table near the bottom and download **"Windows x86 installer"** — this is the 32-bit build (do **not** pick "Windows x86-64 installer," which is 64-bit despite the confusing name overlap). Run the installer:
- Check **"Add python.exe to PATH"** at the bottom of the first screen
- Use the default install location

> **Why exactly 3.9.13?** It's also the last Python release with official Windows 7 support — don't substitute a newer version even though it might install fine on this dev PC, since production runs on Windows 7.

**0.4 — Build the bridge's own venv, from inside `sage-bridge\`:**
```powershell
cd "C:\Users\DELL\Desktop\Moe\Chat Assisant  placeware x1\sage-bridge"
py -3.9-32 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt
```
This creates a `sage-bridge\.venv` folder — separate and independent from `backend\.venv`.

**0.5 — Confirm it's really 32-bit before going further:**
```powershell
.venv\Scripts\python -c "import struct; print(struct.calcsize('P')*8)"
```
Must print `32`.

> **From here on, every command in this walkthrough that starts with `.venv\Scripts\activate` means *this* venv** — always run it from inside `sage-bridge\`, in a fresh terminal, never a window where you previously activated `backend\.venv`.

**Checklist:**
- [ ] `sage-bridge\.venv` exists (separate from `backend\.venv`)
- [ ] `sage-bridge\.venv\Scripts\python.exe` reports `32`-bit
- [ ] `pip install -r requirements.txt` completed with no errors

---

## PHASE A — Generate and Set the Bridge API Key

**Why this matters:** the bridge checks every incoming request for this key before doing anything with it. ACE reads its own copy of the same key and sends it along whenever it calls the bridge. If the two don't match character-for-character, every call between them fails.

**A1 — Generate a new key.** Open PowerShell:
```powershell
cd "C:\Users\DELL\Desktop\Moe\Chat Assisant  placeware x1\sage-bridge"
.venv\Scripts\activate
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
This prints one long random line, e.g. `Xk3x9F7qP...` (yours will be different). **Select and copy it** — you'll paste it into two files next.

**A2 — Paste it into `sage-bridge\.env`.**
```powershell
notepad .env
```
Find this line:
```
BRIDGE_API_KEY=placeware-bridge-dev-key-2026
```
Replace everything after the `=` with the string you copied in A1:
```
BRIDGE_API_KEY=Xk3x9F7qP...your-generated-key...
```
**Ctrl+S** to save, close Notepad.

**A3 — Paste the exact same key into `backend\.env`.**
```powershell
notepad "C:\Users\DELL\Desktop\Moe\Chat Assisant  placeware x1\backend\.env"
```
Find:
```
SAGE_BRIDGE_KEY=placeware-bridge-dev-key-2026
```
Replace the value with the **same string** from A1 (copy-paste it again — don't retype). Save and close.

**Checklist:**
- [ ] `BRIDGE_API_KEY` in `sage-bridge\.env` is the new generated string, not `placeware-bridge-dev-key-2026`
- [ ] `SAGE_BRIDGE_KEY` in `backend\.env` is the exact same string as above

---

## PHASE B — Fix the Network Addresses

**Why this matters (read before editing):** ACE runs *inside Docker containers*. The bridge runs as a normal Windows program *outside* any container (it needs direct access to Sage 50). Because of that split, the word `localhost` means something different depending on which side is talking:

| Who's calling | Address to use | Why |
|---|---|---|
| ACE's backend container, calling the bridge | `host.docker.internal` | Inside a container, `localhost` means "this container" — not the Windows PC it's running on. `host.docker.internal` is Docker's built-in way of saying "the real PC," automatically, no setup needed. |
| The bridge (a normal Windows program), calling ACE | `localhost` | The bridge isn't in a container, so `localhost` correctly means "this PC" — and ACE's web address is published on this PC's ports 80/443, so `localhost` reaches it directly. |

**B1 — Edit `sage-bridge\.env`.** Find:
```
SYNBOT_WEBHOOK_URL=https://192.168.100.84/sage/webhook
```
Change the IP address to `localhost`:
```
SYNBOT_WEBHOOK_URL=https://localhost/sage/webhook
```
Leave `BRIDGE_INSECURE_SKIP_VERIFY=true` untouched — ACE's local HTTPS uses a self-signed certificate (the same "Your connection is not private" warning from Step 10 earlier in this guide), and this setting tells the bridge to accept it instead of refusing to connect.

**B2 — Edit `backend\.env`.** Find:
```
SAGE_BRIDGE_URL=http://192.168.100.15:7070
```
Change it to:
```
SAGE_BRIDGE_URL=http://host.docker.internal:7070
```

**Checklist:**
- [ ] `SYNBOT_WEBHOOK_URL` in `sage-bridge\.env` says `localhost`, no IP address left over
- [ ] `SAGE_BRIDGE_URL` in `backend\.env` says `host.docker.internal`, no IP address left over

---

## PHASE C — Confirm the Sage Connection Details

If your teammate already configured the ODBC DSN and company path on this machine, this phase is a quick double-check rather than fresh setup — but do it anyway, since a stale placeholder here fails silently (the bridge starts fine, it just can't see any Sage data).

**C1 — Confirm `SAGE_COMPANY_PATH`.**

*How to find the correct value:* open Sage 50 → menu bar → **Help → About Sage 50 Accounting**. A window pops up showing the company data folder, something like `C:\Sage\Peachtree\Company\YourCompanyName\`. Copy that exact path, including the company folder name at the end.

In `sage-bridge\.env`, find:
```
SAGE_COMPANY_PATH=c:\Sage\Peachtree\Company
```
If it's missing the company folder name, or points somewhere else entirely, replace it with what Sage's About window showed you.

**C2 — Confirm `SAGE_ODBC_DSN`.**

*How to find the correct value:*
1. Open File Explorer, paste this into the address bar, press Enter: `C:\Windows\SysWOW64\odbcad32.exe`
   > **Important — do not use the regular ODBC tool** (the one you'd find by searching Windows normally). That one is 64-bit, and Sage 50 2013's database driver is 32-bit only — the DSN you need is completely invisible in the 64-bit tool, even though it exists. This is the single most common thing that trips people up here.
2. Click the **System DSN** tab.
3. Look for an entry whose driver is "Pervasive ODBC Client Interface." The **Name** column next to it is the value you need.

In `sage-bridge\.env`, find:
```
SAGE_ODBC_DSN=demodata
```
Replace `demodata` with the Name you just found (commonly `PervasiveSage50`, but use whatever is actually listed on your machine).

**C3 — Confirm the SDK file exists.** This DLL is what lets the bridge write acknowledgements back to Sage. In PowerShell:
```powershell
Test-Path "C:\Program Files (x86)\Sage\Peachtree\API\Sage.Peachtree.API.dll"
```
Should print `True`. If it prints `False`, open `C:\Program Files (x86)\Sage\` in File Explorer, search for `Sage.Peachtree.API.dll`, and update `SAGE_API_DLL_PATH` in `sage-bridge\.env` to wherever you actually find it.

**Checklist:**
- [ ] `SAGE_COMPANY_PATH` matches Sage's own About window exactly
- [ ] `SAGE_ODBC_DSN` matches the Name column in the **32-bit** ODBC admin tool
- [ ] `Test-Path` on the SDK DLL printed `True`

---

## PHASE D — Start ACE (the Docker Side)

**D1 — Bring the containers up.** From PowerShell:
```powershell
cd "C:\Users\DELL\Desktop\Moe\Chat Assisant  placeware x1\backend"
docker compose up -d
```
No `--build` needed unless you changed backend code — the images already exist from earlier work, so this comes up in under a minute.

**D2 — Confirm everything is healthy:**
```powershell
docker compose ps
```
Expected — every row shows `Up` or `(healthy)`:
```
NAME                    STATUS
backend-db-1            Up (healthy)
chat-backend.v1         Up (healthy)
placeware-frontend.v1   Up (healthy)
```
If `chat-backend.v1` isn't healthy after a minute or two, it likely just needs the `.env` edits from Phases A/B reloaded:
```powershell
docker compose restart backend
```

**D3 — Confirm the duplicate-event guard exists.** This is a small database table that stops ACE from double-processing the same invoice if the bridge ever retries a delivery:
```powershell
docker exec backend-db-1 psql -U postgres -d synbot_demo -c "SELECT to_regclass('public.placeware_sage_event_log');"
```
Expected — a line containing `placeware_sage_event_log`. If it prints blank instead, create it once:
```powershell
Get-Content ..\backend\migrations\071_sage_bridge_idempotency.sql -Raw | docker exec -i backend-db-1 psql -U postgres -d synbot_demo
```
(If you skip this and the table is missing, the test will still work — ACE just won't catch a duplicate delivery as cleanly.)

**Checklist:**
- [ ] `docker compose ps` shows all three containers `Up`/`(healthy)`
- [ ] The dedupe-table check returns `placeware_sage_event_log`

---

## PHASE E — Start Sage and the Bridge

**E1 — Open Sage 50**, log into your company, and **leave it open** — the bridge needs it running for the rest of this test.

**E2 — Start the bridge.** Open a new PowerShell window (keep it open — this is where you'll watch the invoice get picked up later):
```powershell
cd "C:\Users\DELL\Desktop\Moe\Chat Assisant  placeware x1\sage-bridge"
.venv\Scripts\activate
python main.py
```
Expected — a startup banner like `=== Sage Bridge 2.0.0 starting (mock=False) ===`, and **no `ValidationError`**. If you see the same error as before, go back to Phase A — the key wasn't saved, or was saved with a stray space or line break.

**E3 — Check the bridge is alive.** Open *another* new PowerShell window (don't close E2's — it needs to keep running):
```powershell
curl http://localhost:7070/health
```
Expected — JSON containing `"status":"ok"` and `"odbc_connected":true`. If `odbc_connected` shows `false`, go back to Phase C — the company path or DSN name is off.

**Checklist:**
- [ ] `python main.py` (E2) is running with no errors, window left open
- [ ] `/health` shows `status: ok` and `odbc_connected: true`

---

## PHASE F — Run the Full Connectivity Check

This is an automated script that checks everything at once — both directions, bridge-to-Sage and bridge-to-ACE — before you touch any real data.

**F1 —** in the same window as E3:
```powershell
python test_connectivity.py --skip-write
```
The `--skip-write` flag means "don't create a test customer record inside my real Sage company file" — since this is your actual local Sage install and not a disposable demo copy, keep this flag on.

**F2 — Read the output.** It runs 6 checks in order:
1. Bridge is reachable
2. API key is accepted
3. Sage is reachable through the bridge (ODBC)
4. Bridge can pull real Sage data (customers, inventory)
5. ACE is reachable from this machine
6. ACE's webhook endpoint accepts a push from the bridge

**All 6 should say PASS.** If #5 or #6 fails, go back to Phase B (an old IP address is probably still sitting in one of the `.env` files). If #3 fails, go back to Phase C.

**Checklist:**
- [ ] All 6 checks report PASS

---

## PHASE G — The Real Test: Add an Invoice in Sage

This is the moment the whole setup has been building to.

**G1 —** In the Sage 50 window from E1, create a normal invoice for any existing customer — a small, throwaway amount is fine. Save it.

**G2 — Watch the bridge's log window (E2).** By default the bridge checks for changes every 60 seconds (`WATCHER_POLL_SECONDS=60` in `.env`), so within about a minute you should see a log line saying it found the new invoice and sent it toward ACE.

**G3 — Confirm ACE actually received it.** Pick whichever of these three is easiest for you:

*Option 1 — watch backend logs live* (new PowerShell window):
```powershell
cd "C:\Users\DELL\Desktop\Moe\Chat Assisant  placeware x1\backend"
docker compose logs -f backend
```
Look for a line like `POST /sage/webhook ... 200` or `... 201`.

*Option 2 — check the database directly:*
```powershell
docker exec backend-db-1 psql -U postgres -d synbot_demo -c "SELECT sage_id, customer_id, amount, created_at FROM sage_invoices_cache ORDER BY created_at DESC LIMIT 5;"
```
Your new invoice should be the top row, with a `created_at` timestamp matching right now.

*Option 3 — check it in the ACE web app:* log into `https://localhost`, go to **Finance → AR & Alerts** (or the **Sage Import** page), and look for the new invoice.

**Checklist:**
- [ ] The new invoice shows up in the backend logs, the database, or the ACE UI

**G4 — Clean up.** This created a real record in your Sage company file — delete or void it in Sage 50 now if it was only for testing.

---

## Verification Summary

- **Phase 0.5** — the bridge's venv reports `32`-bit → running under the correct interpreter.
- **Phase A/E2** — `python main.py` starts cleanly with no `ValidationError` → the key fix worked.
- **Phase E3** — `/health` reports `odbc_connected: true` (no architecture-mismatch errors in the log) → the bridge is really talking to Sage, not running blind.
- **Phase F** — `test_connectivity.py --skip-write` passes all 6 checks → both directions of the connection work, confirmed *before* touching real invoice data.
- **Phase G3** — the test invoice lands in `sage_invoices_cache` / the backend logs / the ACE UI → the complete loop works: Sage 50 → ODBC watcher → bridge outbox → webhook → ACE.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ValidationError: BRIDGE_API_KEY is unset or still a placeholder` | Key wasn't actually saved, or saved to the wrong file | Redo Phase A — reopen the file and confirm the value after `=` isn't the old placeholder |
| `Failed to load Sage SDK DLL ... incorrect format` | Running under a 64-bit Python interpreter | Redo Phase 0 — confirm `sage-bridge\.venv\Scripts\python.exe` reports `32`-bit, and that this terminal window never had `backend\.venv` activated |
| `ODBC connection failed: ('IM014', ... architecture mismatch ...)` | Same as above — 64-bit Python against the 32-bit Pervasive driver | Same fix as above — this and the SDK error are two symptoms of the identical root cause |
| `/health` shows `odbc_connected: false` (after confirming Python is 32-bit) | Wrong DSN name, or Sage isn't open | Recheck Phase C2 (DSN name via the **32-bit** ODBC tool); confirm Sage 50 is open and logged in |
| `test_connectivity.py` check 5 or 6 fails ("unreachable") | An old IP address is still set somewhere, or ACE isn't running | Recheck Phase B for leftover `192.168.x.x` values; confirm `docker compose ps` shows everything healthy |
| Bridge never logs picking up the invoice | Watcher hasn't polled yet, or wrong company path | Wait a full 60 seconds; recheck Phase C1 (company path) |
| Backend logs show `401` or `403` on `/sage/webhook` | The two API keys don't match exactly (extra space, partial paste) | Recopy the key from Phase A into both files — don't retype it by hand |

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
| Data load fails: "table does not exist" / "relation ... does not exist" | Backend code is older than the dump — push from the dev laptop, `git pull` + redeploy (migrations up to 139 must run), then retry Step 10b from Step 5 |
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
