Tomorrow's Deployment Walkthrough
What you need before you leave today
A USB drive or file transfer method ready (for the SQL dump)
The deploy/.env file filled in with real values (check deploy/.env.example — mainly set POSTGRES_PASSWORD, JWT_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD, DEEPSEEK_API_KEY)
PART 1 — Install & Start RoyanHealth on the Server
Open Command Prompt as Administrator on the client's server.

Step 1 — Install Git and Docker Desktop (skip if already installed)


winget install Git.Git
winget install Docker.DockerDesktop
After Docker Desktop installs, restart the machine, reopen CMD as Administrator, then wait for Docker Desktop to show "Engine running" in the system tray.

Step 2 — Clone the repo


cd C:\
git clone https://github.com/MofeAkinolaPSE/RoyanSynbot.git
cd RoyanSynbot
Step 3 — Verify your .env is in the deploy folder


dir deploy\.env
If it only shows .env.example, copy and fill it in:


copy deploy\.env.example deploy\.env
notepad deploy\.env
The critical values to fill in are: POSTGRES_PASSWORD, JWT_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD. Everything else can stay as defaults for today.

Step 4 — Build and start the full stack


cd C:\RoyanSynbot\deploy
docker compose up --build -d
This builds all images and starts: PostgreSQL, backend API, frontend, nginx. The migrations run automatically — PostgreSQL runs all .sql files from backend/migrations/ on first start.

Step 5 — Watch it start up (takes 2–4 minutes on first run)


docker compose ps
Wait until all services show healthy. You can also watch logs:


docker compose logs -f backend
When you see Application startup complete — the backend is up.

Step 6 — Verify it's working
Open a browser on the server: http://localhost — you should see the RoyanHealth login screen.

PART 2 — Get the Data Dump from IT
While the stack is starting (or after it's up), sit with Seun Akinkla (IT).

Ask him to run this on the DRM Hope server:


mysqldump -u root -p hope_db > C:\hope_export.sql
He'll be prompted for the MySQL root password. The file hope_export.sql is the dump.

Copy it onto the RoyanHealth server (USB, network share, or direct transfer):


copy \\HOPE-SERVER\share\hope_export.sql C:\RoyanSynbot\data-assimilation\hope_export.sql
If they can't do a mysqldump: Ask Seun to export each module's data as CSV from DRM Hope's Reports/Export menu. Put all the CSVs in a folder: C:\RoyanSynbot\data-assimilation\hope_csvs\

PART 3 — Discover the Schema, Then Load the Data
The ingestion runs inside Docker (no Python install needed on the server).

Open a second Command Prompt window. Keep the first one showing docker compose logs.

Step 7 — Run schema discovery (zero writes, completely safe)


cd C:\RoyanSynbot

docker run --rm ^
  --network deploy_royan_net ^
  -v "C:\RoyanSynbot\data-assimilation":/dal ^
  python:3.12-slim ^
  bash -c "cd /dal && pip install -r requirements.txt -q && python ingest.py --source dump --file hope_export.sql --step discover"
This prints every table name and every column name found in the dump. Copy the output and send it to me (Claude). I'll update field_maps.py with the real column names before you run the load.

(CSV fallback: replace --source dump --file hope_export.sql with --source csv --folder hope_csvs)

Step 8 — After Claude updates field_maps.py — run a dry run


docker run --rm ^
  --network deploy_royan_net ^
  -v "C:\RoyanSynbot\data-assimilation":/dal ^
  -e DATABASE_URL=postgresql://royan:royan_secure_pass@db:5432/royan_hospital ^
  python:3.12-slim ^
  bash -c "cd /dal && pip install -r requirements.txt -q && python ingest.py --source dump --file hope_export.sql --entity patients --dry-run"
Dry run shows what would load. Verify a few patient names look right. No DB writes.

Step 9 — Run the full load


docker run --rm ^
  --network deploy_royan_net ^
  -v "C:\RoyanSynbot\data-assimilation":/dal ^
  -e DATABASE_URL=postgresql://royan:royan_secure_pass@db:5432/royan_hospital ^
  python:3.12-slim ^
  bash -c "cd /dal && pip install -r requirements.txt -q && python ingest.py --source dump --file hope_export.sql --entity all"
You'll see:


[1/4] Extracting raw data from source...
[2/4] Staging raw data to SQLite...
[3/4] Transforming staged data...
[4/4] Loading into RoyanHealth database...

INGESTION COMPLETE
  patients        2,847 seen, 2,847 upserted
  appointments    14,203 seen, 14,203 upserted
  admissions      1,104 seen, 1,104 upserted
  lab             8,901 seen, 8,901 upserted
  pharmacy        6,205 seen, 6,205 upserted
  billing         9,340 seen, 9,340 upserted
If POSTGRES_PASSWORD in your .env is different from the default royan_secure_pass, change it in the -e DATABASE_URL=... flag above.

PART 4 — Verify and Go Live
Step 10 — Open RoyanHealth and verify the data

On the server: http://localhost → log in with the ADMIN_EMAIL / ADMIN_PASSWORD from your .env

Go to Patients — you should see real patient records from DRM Hope
Search for a patient you know exists — confirm name, date of birth, HMO
Step 11 — If something looks wrong with the data

Run it again — it's safe, upserts won't duplicate:


docker run --rm ... python ingest.py --source dump --file hope_export.sql --entity patients
Or for a specific problem, send me the output and I'll fix field_maps.py.

Step 12 — You're live

DRM Hope stays running as before — staff can still use it. Simultaneously, new registrations and encounters are entered into RoyanHealth. The live bridge sync (hope-bridge/) plugs in as Phase 2 once the site visit confirms the ODBC schema.

Quick reference for the day:

Command	What it does
docker compose up --build -d	Start the full stack (run from deploy/)
docker compose ps	Check all services are healthy
docker compose logs -f backend	Watch backend logs
docker compose down	Stop everything
ingest --step discover	Show dump schema — no writes
ingest --dry-run	Show what would load — no writes
ingest --entity all	Load all data into PostgreSQL