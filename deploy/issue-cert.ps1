<#
  issue-cert.ps1 - Get a real (browser-trusted) HTTPS certificate for ACE from Let's Encrypt.

  Run ONCE on the ACE server (the machine the domain points to - 192.168.0.112), in PowerShell:

      cd "<the ACE folder>"
      powershell -ExecutionPolicy Bypass -File .\deploy\issue-cert.ps1 -Email you@placeware.com

  What it does (everything runs inside Docker - no Ubuntu/WSL needed):
    1. Starts the web server and the certbot service with the current settings
    2. Checks the web server can serve Let's Encrypt's check file
    3. Practice run against Let's Encrypt's TEST servers (proves the internet can reach you)
    4. Gets the real certificate
    5. Installs it where the web server already looks, and reloads the web server
  Renewal is automatic afterwards (the certbot service checks twice a day).

  Safe to run again: if a valid certificate already exists it is kept.
#>
param(
    [Parameter(Mandatory = $true)][string]$Email,
    [string]$Domain = "placewareaiapp.online",
    [switch]$IncludeWww,
    [switch]$SkipPractice
)

# Docker prints normal progress on stderr; Windows PowerShell would treat that as an error.
# Every step checks Docker's exit code instead.
$ErrorActionPreference = "Continue"
function Step($n, $text) { Write-Host ""; Write-Host "[$n] $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "    OK  $text" -ForegroundColor Green }
function Fail($text, $help) {
    Write-Host "    FAILED  $text" -ForegroundColor Red
    if ($help) { Write-Host "    $help" -ForegroundColor Yellow }
    Pop-Location -ErrorAction SilentlyContinue
    exit 1
}

$backend = Join-Path $PSScriptRoot "..\backend"
if (-not (Test-Path (Join-Path $backend "docker-compose.yml"))) { Fail "Can't find backend\docker-compose.yml next to the deploy folder." "Run the script from inside the ACE folder." }
Push-Location $backend

$domains = @("-d", $Domain)
if ($IncludeWww) { $domains += @("-d", "www.$Domain") }

# 1 ------------------------------------------------------------------------------------------
Step 1 "Starting the web server and certbot with the current settings"
docker version --format "{{.Server.Version}}" *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker is not running." "Open Docker Desktop, wait until it says 'Engine running', then run this again." }
docker compose up -d certs-init frontend certbot
if ($LASTEXITCODE -ne 0) { Fail "Could not start the containers." "Check Docker Desktop for errors, then run again." }
Start-Sleep -Seconds 8
Ok "web server and certbot are running"

# 2 ------------------------------------------------------------------------------------------
Step 2 "Checking the web server serves Let's Encrypt's check folder"
docker compose run --rm --entrypoint sh certbot -c "mkdir -p /var/www/certbot/.well-known/acme-challenge && echo ace-ok > /var/www/certbot/.well-known/acme-challenge/ace-check" | Out-Null
try {
    $c = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 "http://localhost/.well-known/acme-challenge/ace-check").Content
    # served as a plain file, so PowerShell may hand back raw bytes
    $r = if ($c -is [byte[]]) { [System.Text.Encoding]::ASCII.GetString($c).Trim() } else { "$c".Trim() }
} catch { $r = "" }
if ($r -ne "ace-ok") { Fail "The web server did not return the check file." "The frontend container may be running old settings. Run:  docker compose up -d --force-recreate frontend  and try again." }
Ok "check folder is served on port 80"

# 3 ------------------------------------------------------------------------------------------
if (-not $SkipPractice) {
    Step 3 "Practice run with Let's Encrypt's TEST servers (nothing is changed)"
    docker compose run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot @domains `
        --email $Email --agree-tos --no-eff-email --non-interactive --dry-run
    if ($LASTEXITCODE -ne 0) {
        Fail "Let's Encrypt could not reach this server on port 80 for $Domain." `
            "Check: (a) the domain's DNS A record points to the office public IP, (b) the MikroTik and TP-Link port-80 forwarding rules (GO-LIVE-DOMAIN.md Steps 3-5), (c) Windows Firewall allows port 80. Test from a phone on mobile data: http://$Domain/.well-known/acme-challenge/ace-check should show 'ace-ok'."
    }
    Ok "Let's Encrypt can reach this server - practice run passed"
}

# 4 ------------------------------------------------------------------------------------------
Step 4 "Getting the real certificate"
docker compose run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot @domains `
    --email $Email --agree-tos --no-eff-email --non-interactive --keep-until-expiring
if ($LASTEXITCODE -ne 0) { Fail "Let's Encrypt did not issue the certificate." "Read the message above. If it mentions 'too many', wait an hour - Let's Encrypt limits repeated attempts." }
Ok "certificate issued"

# 5 ------------------------------------------------------------------------------------------
Step 5 "Installing it and reloading the web server"
docker compose run --rm --entrypoint sh certbot -c "cp -L /etc/letsencrypt/live/$Domain/fullchain.pem /etc/ssl/placeware/cert.pem && cp -L /etc/letsencrypt/live/$Domain/privkey.pem /etc/ssl/placeware/key.pem && chmod 644 /etc/ssl/placeware/cert.pem && chmod 640 /etc/ssl/placeware/key.pem"
if ($LASTEXITCODE -ne 0) { Fail "Could not copy the certificate into place." "" }
docker exec placeware-frontend.v1 nginx -s reload
if ($LASTEXITCODE -ne 0) { Fail "The web server did not reload." "Run:  docker compose restart frontend" }
docker compose up -d certbot | Out-Null
Ok "certificate installed, web server reloaded, automatic renewal running"

Write-Host ""
docker compose run --rm --entrypoint certbot certbot certificates
Write-Host ""
Write-Host "Done. Open https://$Domain - the padlock should show with no warning." -ForegroundColor Green
Write-Host "(If a browser still warns, close ALL its windows and reopen - it can remember the old certificate.)"
Pop-Location
