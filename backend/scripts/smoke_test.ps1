param([string]$Token = "")

if (-not $Token) {
    # Mint a dev token on the fly
    $Token = (& "$PSScriptRoot\..\venv\Scripts\python.exe" -c @"
import jwt, datetime
secret='change-me-for-dev'
exp=datetime.datetime.utcnow()+datetime.timedelta(hours=1)
tok=jwt.encode({'sub':'smoke-test','roles':['admin','management','ops','finance'],'exp':exp},secret,algorithm='HS256')
print(tok)
"@ 2>$null)
}

$h = @{ Authorization = "Bearer $Token" }
$base = "http://127.0.0.1:8000"
$pass = 0
$fail = 0

function Test-Endpoint {
    param([string]$desc, [string]$path, [bool]$auth=$true, [int[]]$expected=@(200))
    $headers = if ($auth) { $h } else { @{} }
    try {
        $r = Invoke-WebRequest -Uri "$base$path" -Method GET -Headers $headers -UseBasicParsing -TimeoutSec 8 -ErrorAction Stop
        $code = [int]$r.StatusCode
    } catch {
        $code = [int]($_.Exception.Response.StatusCode.value__ )
    }
    $ok = $expected -contains $code
    if ($ok) { $script:pass++ } else { $script:fail++ }
    $tag = if ($ok) { "PASS" } else { "FAIL" }
    Write-Host ("  [{0,-4}] {1,-35} -> HTTP {2}" -f $tag, $desc, $code)
    return $ok, $code
}

Write-Host ""
Write-Host "=== PLACEWARE BACKEND SMOKE PASS  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="
Write-Host ""

# --- Core ---
Test-Endpoint "Health (/)"                          "/"                          $false @(200)
Test-Endpoint "Schema readiness"                    "/controls/readiness"        $true  @(200)
Test-Endpoint "Workflow metrics"                    "/workflow/jobs/metrics"     $true  @(200)

# --- Sage ---
Test-Endpoint "Sage import status"                  "/sage/import/status"        $true  @(200,404)
Test-Endpoint "Sage inventory summary"              "/sage/inventory/summary"    $true  @(200,404)
Test-Endpoint "Sage AR summary"                     "/sage/ar/summary"           $true  @(200,404)

# --- Inventory views (direct DB) ---
Test-Endpoint "Inventory snapshot view"             "/inventory/snapshot"        $true  @(200,404)

# --- Chat ---
Test-Endpoint "Chat health (/chat)"                 "/chat"                      $false @(200,405,422)

Write-Host ""

# Retrieve readiness detail
try {
    $r = Invoke-WebRequest -Uri "$base/controls/readiness" -Headers $h -UseBasicParsing -TimeoutSec 6 -ErrorAction Stop
    $body = $r.Content | ConvertFrom-Json
    Write-Host ("  controls/readiness: ready={0}  reason={1}" -f $body.ready, $body.reason)
} catch {}

# Retrieve workflow metrics detail
try {
    $r = Invoke-WebRequest -Uri "$base/workflow/jobs/metrics" -Headers $h -UseBasicParsing -TimeoutSec 6 -ErrorAction Stop
    $body = $r.Content | ConvertFrom-Json
    Write-Host ("  workflow/metrics:   total_jobs={0}  waiting={1}  overdue={2}" -f $body.total_jobs, $body.waiting_jobs, $body.overdue_waiting_jobs)
} catch {}

Write-Host ""
Write-Host ("=== RESULT: {0} passed, {1} failed ===" -f $pass, $fail)
if ($fail -eq 0) {
    Write-Host "  [OK] BACKEND READY FOR SAGE DATA INGESTION"
} else {
    Write-Host "  [!!] $fail endpoint(s) need review before ingestion"
}
Write-Host ""
