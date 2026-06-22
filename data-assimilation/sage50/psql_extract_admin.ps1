# psql_extract_admin.ps1
# Run this as ADMINISTRATOR to extract Sage GL/inventory transaction data.
#
# What this does:
#   1. Creates a 32-bit ODBC System DSN for the Pervasive Engine Interface
#   2. Stops the psqlWGE service and kills any residual MKDE processes
#   3. Connects via Pervasive ODBC Engine Interface (DSN=PLANIGLI)
#   4. Extracts JrnlHdr, JrnlRow, InventoryCosts, TaxCode, BankRecords tables
#   5. Saves CSV files to data-assimilation\sage50\extracted\
#   6. Restarts psqlWGE
#
# Run with:   Right-click -> "Run as administrator" or:
#             Start-Process powershell -Verb RunAs -ArgumentList "-File psql_extract_admin.ps1"

Set-Location $PSScriptRoot

$PY32      = 'C:\Users\DELL\AppData\Local\Programs\Python\Python38-32\python.exe'
$JUNC_PATH = 'C:\SageData\planigli'
$OUT_DIR   = "$PSScriptRoot\extracted"
$SVC_NAME  = 'psqlWGE'
$DSN_NAME  = 'PLANIGLI'
$DRV_DLL   = 'C:\Program Files (x86)\Pervasive Software\PSQL\bin\w3odbcei.dll'

# Ensure output dir exists
if (-not (Test-Path $OUT_DIR)) { New-Item -ItemType Directory -Path $OUT_DIR | Out-Null }

# Verify junction exists
if (-not (Test-Path $JUNC_PATH)) {
    New-Item -ItemType Directory -Force -Path 'C:\SageData' | Out-Null
    cmd /c "mklink /J `"$JUNC_PATH`" `"$PSScriptRoot\..\..\..\Installer Files\Sage Data 1\planigli`""
}

# =============================================================================
# Step 1: Create 32-bit System DSN (stored under WOW6432Node for 32-bit ODBC)
# =============================================================================
Write-Host "=== Step 1: Registering 32-bit ODBC DSN '$DSN_NAME' ==="

$iniKey  = "HKLM:\SOFTWARE\WOW6432Node\ODBC\ODBC.INI\$DSN_NAME"
$srcKey  = "HKLM:\SOFTWARE\WOW6432Node\ODBC\ODBC.INI\ODBC Data Sources"

# DSN entry
if (-not (Test-Path $iniKey)) { New-Item -Path $iniKey -Force | Out-Null }
Set-ItemProperty -Path $iniKey -Name 'Driver'      -Value $DRV_DLL
Set-ItemProperty -Path $iniKey -Name 'DBQ'         -Value $JUNC_PATH
Set-ItemProperty -Path $iniKey -Name 'Description' -Value 'Planigli Sage50 Data'
Set-ItemProperty -Path $iniKey -Name 'OpenMode'    -Value 0   # Normal (read/write)

# Data Sources listing
if (-not (Test-Path $srcKey)) { New-Item -Path $srcKey -Force | Out-Null }
Set-ItemProperty -Path $srcKey -Name $DSN_NAME -Value 'Pervasive ODBC Engine Interface'

Write-Host "  DSN '$DSN_NAME' -> $JUNC_PATH  [OK]"

# =============================================================================
# Step 2: Stop psqlWGE and kill residual MKDE processes
# =============================================================================
Write-Host ""
Write-Host "=== Step 2: Stopping psqlWGE service ==="
Stop-Service -Name $SVC_NAME -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 8   # give the engine time to flush and release shared memory

# Kill any residual Pervasive engine processes that might hold shared memory
$mkdeProcs = Get-Process -Name 'w32mkde','pvsw','pvntd' -ErrorAction SilentlyContinue
if ($mkdeProcs) {
    Write-Host "  Stopping residual Pervasive engine processes: $($mkdeProcs.Name -join ', ')"
    $mkdeProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
}

$svc = Get-Service -Name $SVC_NAME
Write-Host "Service status: $($svc.Status)"
if ($svc.Status -ne 'Stopped') {
    Write-Error "Failed to stop $SVC_NAME. Make sure Sage 50 is closed and run as Administrator."
    exit 1
}

# =============================================================================
# Step 3: Extract via ODBC Engine Interface (DSN mode)
# =============================================================================
Write-Host ""
Write-Host "=== Step 3: Extracting via ODBC Engine Interface (DSN=$DSN_NAME) ==="

$pythonScript = @"
import pyodbc, csv, sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

OUT_DIR  = r'$OUT_DIR'
DSN_NAME = '$DSN_NAME'

# Connect via DSN (Engine Interface — works when psqlWGE is stopped)
cs = f'DSN={DSN_NAME};'
print(f'Connecting: {cs}')
try:
    conn = pyodbc.connect(cs, timeout=15)
    print('CONNECTED!')
except Exception as e:
    print(f'ERROR: {e}')
    # Fallback: try explicit driver+path in case DSN has issues
    fallback = r'Driver={Pervasive ODBC Engine Interface};DBQ=C:\SageData\planigli;'
    print(f'Trying fallback: {fallback}')
    try:
        conn = pyodbc.connect(fallback, timeout=15)
        print('CONNECTED via fallback!')
    except Exception as e2:
        print(f'Fallback also failed: {e2}')
        sys.exit(1)

cursor = conn.cursor()

def export_table(table_name, output_file, query=None):
    if query is None:
        query = f'SELECT * FROM {table_name}'
    try:
        cursor.execute(query)
        cols = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        print(f'  {table_name}: {len(rows)} rows -> {output_file}')
        return len(rows)
    except Exception as e:
        print(f'  {table_name}: FAILED - {e}')
        return 0

tables = [
    ('JrnlHdr',          'jrnlhdr.csv'),
    ('JrnlRow',          'jrnlrow.csv'),
    ('InventoryCosts',   'invcost.csv'),
    ('Tax_Code',         'taxcode.csv'),
    ('BankRecords',      'bankrec.csv'),
    ('Budgets',          'budgets.csv'),
    ('LineItem',         'lineitem.csv'),
    ('Vendors',          'vendors.csv'),
    ('Customers',        'customers.csv'),
    ('Chart',            'chart.csv'),
]

total = 0
for tbl, fname in tables:
    n = export_table(tbl, os.path.join(OUT_DIR, fname))
    total += n

print(f'\nTotal rows extracted: {total}')
conn.close()
"@

$pythonScript | & $PY32 2>&1

# =============================================================================
# Step 4: Restart psqlWGE
# =============================================================================
Write-Host ""
Write-Host "=== Step 4: Restarting psqlWGE service ==="
Start-Service -Name $SVC_NAME -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$svc = Get-Service -Name $SVC_NAME
Write-Host "Service status: $($svc.Status)"

Write-Host ""
Write-Host "=== Done ==="
Write-Host "CSV files saved to: $OUT_DIR"
Write-Host "Next step: cd to data-assimilation/ and run: python assimilate_from_csv.py"
