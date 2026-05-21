<#
start_and_test.ps1 - Sage-side helper to start bridge and run connectivity checks.

Usage examples:
  powershell -ExecutionPolicy Bypass -File .\start_and_test.ps1
  powershell -ExecutionPolicy Bypass -File .\start_and_test.ps1 -SkipWrite
  powershell -ExecutionPolicy Bypass -File .\start_and_test.ps1 -OnlyTest

Notes:
  - Run this on the Windows machine where Sage and sage-bridge live.
  - Default behavior starts bridge if needed, waits for /health, then runs test_connectivity.py.
#>

param(
    [switch]$SkipWrite,
    [switch]$OnlyTest,
    [int]$BridgeStartTimeoutSeconds = 45
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[start-and-test] $Message" -ForegroundColor Cyan
}

function Get-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @{ Cmd = "py"; Args = @("-3") }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @{ Cmd = "python"; Args = @() }
    }
    throw "Python not found. Install Python 3 and ensure py or python is on PATH."
}

function Test-BridgeHealth {
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:7070/health" -Method Get -TimeoutSec 3
        return $null -ne $resp
    }
    catch {
        return $false
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$py = Get-PythonCommand
$pyCmd = $py.Cmd
$pyPrefix = $py.Args

Write-Step "Working directory: $scriptDir"

$bridgeAlreadyRunning = Test-BridgeHealth
$startedProcess = $null

if (-not $OnlyTest) {
    if ($bridgeAlreadyRunning) {
        Write-Step "Bridge already reachable on http://127.0.0.1:7070"
    }
    else {
        Write-Step "Starting bridge process (main.py)..."
        $startArgs = @()
        $startArgs += $pyPrefix
        $startArgs += @("main.py")

        $startedProcess = Start-Process -FilePath $pyCmd -ArgumentList $startArgs -PassThru -WorkingDirectory $scriptDir

        $deadline = (Get-Date).AddSeconds($BridgeStartTimeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            if (Test-BridgeHealth) {
                Write-Step "Bridge is healthy."
                break
            }
            Start-Sleep -Milliseconds 700
        }

        if (-not (Test-BridgeHealth)) {
            if ($startedProcess -and -not $startedProcess.HasExited) {
                Stop-Process -Id $startedProcess.Id -Force -ErrorAction SilentlyContinue
            }
            throw "Bridge did not become healthy within $BridgeStartTimeoutSeconds seconds."
        }
    }
}

Write-Step "Running connectivity diagnostic..."
$testArgs = @()
$testArgs += $pyPrefix
$testArgs += @("test_connectivity.py")
if ($SkipWrite) {
    $testArgs += "--skip-write"
}

& $pyCmd @testArgs
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host "[start-and-test] Connectivity checks passed." -ForegroundColor Green
}
else {
    Write-Host "[start-and-test] Connectivity checks failed (exit code: $exitCode)." -ForegroundColor Red
}

if ($startedProcess -and -not $startedProcess.HasExited) {
    Write-Host "[start-and-test] Bridge started by this script remains running (PID: $($startedProcess.Id))." -ForegroundColor Yellow
}

exit $exitCode
