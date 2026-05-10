#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Installs the Sage Bridge as a Windows Service using NSSM so it starts
  automatically on boot — even without a logged-in user.

.DESCRIPTION
  The Placeware Sage Bridge (sage-bridge/main.py) must run continuously on
  the Windows machine where Sage 50 2013 is installed.  This script wraps
  the uvicorn process in NSSM (Non-Sucking Service Manager), which:
    * Starts the bridge on Windows boot
    * Restarts it automatically if it crashes
    * Rotates log files daily

.PREREQUISITES
  1. Python 3.9+ installed (python.exe in PATH)
  2. NSSM downloaded from https://nssm.cc/download
       - Extract ZIP
       - Copy win64\nssm.exe  →  C:\Tools\nssm\nssm.exe
  3. Sage Bridge venv created:
       cd "<path-to-repo>\sage-bridge"
       python -m venv .venv
       .venv\Scripts\pip install -r requirements.txt
  4. sage-bridge\.env filled in (copy from .env.example)

.USAGE
  Open PowerShell as Administrator, then run:
    .\sage-bridge\install-service.ps1

  To uninstall:
    .\sage-bridge\install-service.ps1 -Uninstall
#>
param(
    [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Paths ─────────────────────────────────────────────────────────────────────
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$BridgeRoot  = $ScriptDir                                      # sage-bridge/
$NssmExe     = "C:\Tools\nssm\nssm.exe"
$PythonExe   = Join-Path $BridgeRoot ".venv\Scripts\python.exe"
$LogDir      = Join-Path $BridgeRoot "logs"

# ── Service settings ──────────────────────────────────────────────────────────
$ServiceName = "PlacewareSageBridge"
$DisplayName = "Placeware Sage Bridge"
$Description = "Bridges the PlacewareBot AI assistant with Sage 50 Peachtree data."
$BridgeHost  = "0.0.0.0"
$BridgePort  = "7070"

# ── Pre-flight checks ─────────────────────────────────────────────────────────
function Assert-File($path, $message) {
    if (-not (Test-Path $path)) {
        Write-Error $message
        exit 1
    }
}

Assert-File $NssmExe @"
NSSM not found at: $NssmExe

Download NSSM (free, open-source):
  1. Go to https://nssm.cc/download
  2. Download the latest ZIP
  3. Extract and copy win64\nssm.exe to C:\Tools\nssm\nssm.exe
  4. Re-run this script.
"@

Assert-File $PythonExe @"
Python venv not found at: $PythonExe

Create the venv first (run in cmd/PowerShell from the sage-bridge folder):
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
"@

Assert-File (Join-Path $BridgeRoot ".env") @"
sage-bridge\.env not found.

Copy .env.example to .env and fill in the values:
  SAGE_COMPANY_PATH  - path to the Sage 50 company data folder
  SAGE_ODBC_DSN      - name of the Pervasive ODBC DSN you created
  SAGE_MOCK          - set to false for live mode
  BRIDGE_API_KEY     - must match SAGE_BRIDGE_KEY in backend/.env
  SYNBOT_WEBHOOK_URL - http://<VM LAN IP>:8000/sage/webhook
"@

# ── Uninstall path ────────────────────────────────────────────────────────────
if ($Uninstall) {
    Write-Host "Stopping and removing service '$ServiceName'..."
    & $NssmExe stop    $ServiceName 2>$null
    Start-Sleep -Seconds 2
    & $NssmExe remove  $ServiceName confirm
    Write-Host "Service '$ServiceName' removed."
    exit 0
}

# ── Remove existing service (clean reinstall) ─────────────────────────────────
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Service '$ServiceName' already exists — removing for clean reinstall..."
    & $NssmExe stop    $ServiceName 2>$null
    Start-Sleep -Seconds 2
    & $NssmExe remove  $ServiceName confirm
    Start-Sleep -Seconds 1
}

# ── Create log directory ──────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# ── Install service ───────────────────────────────────────────────────────────
Write-Host "Installing '$ServiceName'..."

# The command NSSM will run: python -m uvicorn main:app --host 0.0.0.0 --port 7070
& $NssmExe install $ServiceName $PythonExe `
    "-m uvicorn main:app --host $BridgeHost --port $BridgePort"

& $NssmExe set $ServiceName DisplayName    $DisplayName
& $NssmExe set $ServiceName Description   $Description
& $NssmExe set $ServiceName AppDirectory  $BridgeRoot

# Logging — rotate daily, keep 7 days
& $NssmExe set $ServiceName AppStdout        (Join-Path $LogDir "bridge_out.log")
& $NssmExe set $ServiceName AppStderr        (Join-Path $LogDir "bridge_err.log")
& $NssmExe set $ServiceName AppRotateFiles   1
& $NssmExe set $ServiceName AppRotateOnline  1
& $NssmExe set $ServiceName AppRotateSeconds 86400
& $NssmExe set $ServiceName AppRotateBytes   52428800   # 50 MB per file

# Restart policy — restart after 3s if it crashes
& $NssmExe set $ServiceName AppRestartDelay  3000

# Run as LocalSystem (full access to COM + Sage registry entries)
& $NssmExe set $ServiceName ObjectName       LocalSystem

# Auto-start on boot
& $NssmExe set $ServiceName Start            SERVICE_AUTO_START

# ── Start the service ─────────────────────────────────────────────────────────
Write-Host "Starting '$ServiceName'..."
& $NssmExe start $ServiceName
Start-Sleep -Seconds 4

$svc = Get-Service -Name $ServiceName

Write-Host ""
Write-Host "======================================================="
Write-Host " Sage Bridge Windows Service — Installed"
Write-Host "======================================================="
Write-Host " Service : $ServiceName"
Write-Host " Status  : $($svc.Status)"
Write-Host " Port    : $BridgePort"
Write-Host " Logs    : $LogDir"
Write-Host ""
Write-Host " Useful commands:"
Write-Host "   Start    : net start $ServiceName"
Write-Host "   Stop     : net stop $ServiceName"
Write-Host "   Reinstall: .\sage-bridge\install-service.ps1"
Write-Host "   Remove   : .\sage-bridge\install-service.ps1 -Uninstall"
Write-Host ""
Write-Host " Verify bridge is running:"
Write-Host "   curl http://localhost:7070/health"
Write-Host "======================================================="

if ($svc.Status -ne "Running") {
    Write-Warning "Service installed but not Running (status: $($svc.Status))."
    Write-Warning "Check logs at $LogDir\bridge_err.log for startup errors."
}
