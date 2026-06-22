"""
Load extracted GL journal data into Postgres sage_gl_transactions table.
Source: jrnlrow_final.csv (date, gl_account, description)
"""
import csv
import os
import sys

try:
    from supabase import create_client
except ImportError:
    os.system('pip install supabase --quiet')
    from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    # Try reading from docker env
    import subprocess
    result = subprocess.run(
        ['docker', 'exec', 'chat-backend.v1', 'env'],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if line.startswith('SUPABASE_URL='):
            SUPABASE_URL = line.split('=', 1)[1]
        elif line.startswith('SUPABASE_SERVICE_KEY=') or line.startswith('SUPABASE_KEY='):
            SUPABASE_KEY = line.split('=', 1)[1]

print("Connecting to Supabase:", SUPABASE_URL[:40] + "..." if SUPABASE_URL else "MISSING")
if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL / SUPABASE_KEY not set")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Create table if not exists via RPC
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS sage_gl_transactions (
    id SERIAL PRIMARY KEY,
    post_date DATE,
    gl_account VARCHAR(20),
    description TEXT,
    source VARCHAR(20) DEFAULT 'sage50',
    imported_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_gl_transactions_date ON sage_gl_transactions(post_date);
CREATE INDEX IF NOT EXISTS idx_gl_transactions_acct ON sage_gl_transactions(gl_account);
"""

try:
    sb.rpc('exec_sql', {'query': CREATE_SQL}).execute()
    print("Table created/verified")
except Exception as e:
    print("Table create note:", str(e)[:100])

# Load CSV
CSV_PATH = os.path.join(os.path.dirname(__file__), 'extracted', 'jrnlrow_final.csv')
rows = []
with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        if not row['date']:
            continue
        # Only load records with meaningful descriptions or GL accounts
        desc = row['description'].strip()
        acct = row['gl_account'].strip()
        # Filter out garbage descriptions (< 5 chars or non-printable)
        if desc and len(desc) < 4:
            desc = ''
        rows.append({
            'post_date': row['date'],
            'gl_account': acct if acct else None,
            'description': desc if desc else None,
        })

print("Records to load: %d" % len(rows))

# Batch upsert in chunks of 500
BATCH = 500
loaded = 0
errors = 0
for i in range(0, len(rows), BATCH):
    chunk = rows[i:i+BATCH]
    try:
        sb.table('sage_gl_transactions').upsert(chunk, on_conflict='post_date,description').execute()
        loaded += len(chunk)
        if loaded % 5000 == 0:
            print("  Loaded %d / %d" % (loaded, len(rows)))
    except Exception as e:
        # Try insert instead
        try:
            sb.table('sage_gl_transactions').insert(chunk).execute()
            loaded += len(chunk)
        except Exception as e2:
            errors += len(chunk)
            if errors < 20:
                print("  Error: %s" % str(e2)[:100])

print("Done. Loaded: %d, Errors: %d" % (loaded, errors))

# Verify
res = sb.table('sage_gl_transactions').select('count', count='exact').execute()
print("Total rows in DB: %d" % res.count)
