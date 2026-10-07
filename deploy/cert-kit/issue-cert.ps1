<#
  issue-cert.ps1 - Get a real (browser-trusted) HTTPS certificate from Let's Encrypt for any
  Docker Compose app whose web server is nginx. Reusable version of the Placeware script.

  Run ONCE on the server the domain points to, in PowerShell, from the folder that holds
  docker-compose.yml (or pass -ComposeDir):

      powershell -ExecutionPolicy Bypass -File .\deploy\issue-cert.ps1 -Email it@client.com -Domain app.client.com

  Needs the compose setup described in GO-LIVE-CERTIFICATE.md (Part A): a certbot service,
  a shared webroot volume served by nginx on port 80, and a shared certificate volume nginx
  reads from.

  What it does (everything runs inside Docker - no WSL/Linux tools needed):
    1. Starts the web server and the certbot service
    2. Checks the web server serves Let's Encrypt's check folder on port 80
    3. Practice run against Let's Encrypt's TEST servers (proves the internet can reach you)
    4. Gets the real certificate
    5. Copies it to where nginx already looks, and reloads nginx (no downtime)
  Renewal is automatic afterwards (the certbot service checks twice a day).
  Safe to run again: a valid certificate is kept, not re-issued.
#>
param(
    [Parameter(Mandatory = $true)][string]$Email,
    [Parameter(Mandatory = $true)][string]$Domain,
    [string]$ComposeDir = ".",              # folder containing docker-compose.yml
    [string]$WebService = "frontend",       # compose service running nginx
    [string]$CertbotService = "certbot",    # compose service running certbot
    [string]$InitService = "certs-init",    # optional self-signed bootstrap service ("" to skip)
    [string]$CertDir = "/etc/ssl/app",      # where nginx reads the certificate (inside both containers)
    [string]$CertFile = "cert.pem",
    [string]$KeyFile = "key.pem",
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

if (-not (Test-Path (Join-Path $ComposeDir "docker-compose.yml"))) {
    Fail "No docker-compose.yml in '$ComposeDir'." "Run from the app's compose folder, or pass -ComposeDir <folder>."
}
Push-Location $ComposeDir

$domains = @("-d", $Domain)
if ($IncludeWww) { $domains += @("-d", "www.$Domain") }

# 1 ------------------------------------------------------------------------------------------
Step 1 "Starting the web server and certbot"
docker version --format "{{.Server.Version}}" *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker is not running." "Open Docker Desktop, wait until it says 'Engine running', then run this again." }
$services = @(docker compose config --services)
foreach ($s in @($WebService, $CertbotService)) {
    if ($services -notcontains $s) { Fail "docker-compose.yml has no '$s' service." "Add it (GO-LIVE-CERTIFICATE.md Part A) or pass the right name with -WebService / -CertbotService." }
}
$toStart = @($WebService, $CertbotService)
if ($InitService -and ($services -contains $InitService)) { $toStart = @($InitService) + $toStart }
docker compose up -d @toStart
if ($LASTEXITCODE -ne 0) { Fail "Could not start the containers." "Check Docker Desktop for errors, then run again." }
Start-Sleep -Seconds 8
Ok "web server and certbot are running"

# 2 ------------------------------------------------------------------------------------------
Step 2 "Checking the web server serves Let's Encrypt's check folder"
docker compose run --rm --entrypoint sh $CertbotService -c "mkdir -p /var/www/certbot/.well-known/acme-challenge && echo cert-ok > /var/www/certbot/.well-known/acme-challenge/cert-check" | Out-Null
try {
    $c = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 "http://localhost/.well-known/acme-challenge/cert-check").Content
    # served as a plain file, so PowerShell may hand back raw bytes
    $r = if ($c -is [byte[]]) { [System.Text.Encoding]::ASCII.GetString($c).Trim() } else { "$c".Trim() }
} catch { $r = "" }
if ($r -ne "cert-ok") {
    Fail "The web server did not return the check file." "Check the nginx port-80 block has the /.well-known/acme-challenge/ location (Part A3) and the web service mounts the webroot volume, then run:  docker compose up -d --force-recreate $WebService"
}
Ok "check folder is served on port 80"

# 3 ------------------------------------------------------------------------------------------
if (-not $SkipPractice) {
    Step 3 "Practice run with Let's Encrypt's TEST servers (nothing is changed)"
    docker compose run --rm --entrypoint certbot $CertbotService certonly --webroot -w /var/www/certbot @domains `
        --email $Email --agree-tos --no-eff-email --non-interactive --dry-run
    if ($LASTEXITCODE -ne 0) {
        Fail "Let's Encrypt could not reach this server on port 80 for $Domain." `
            "Check: (a) the domain's DNS A record points to the site's public IP, (b) the router forwards port 80 to this server (Part B), (c) Windows Firewall allows port 80 inbound. Test from a phone on mobile data: http://$Domain/.well-known/acme-challenge/cert-check should show 'cert-ok'."
    }
    Ok "Let's Encrypt can reach this server - practice run passed"
}

# 4 ------------------------------------------------------------------------------------------
Step 4 "Getting the real certificate"
docker compose run --rm --entrypoint certbot $CertbotService certonly --webroot -w /var/www/certbot @domains `
    --email $Email --agree-tos --no-eff-email --non-interactive --keep-until-expiring
if ($LASTEXITCODE -ne 0) { Fail "Let's Encrypt did not issue the certificate." "Read the message above. If it mentions 'too many', wait an hour - Let's Encrypt limits repeated attempts." }
Ok "certificate issued"

# 5 ------------------------------------------------------------------------------------------
Step 5 "Installing it and reloading the web server"
docker compose run --rm --entrypoint sh $CertbotService -c "cp -L /etc/letsencrypt/live/$Domain/fullchain.pem $CertDir/$CertFile && cp -L /etc/letsencrypt/live/$Domain/privkey.pem $CertDir/$KeyFile && chmod 644 $CertDir/$CertFile && chmod 640 $CertDir/$KeyFile"
if ($LASTEXITCODE -ne 0) { Fail "Could not copy the certificate into place." "Check the certbot service mounts the certificate volume at $CertDir (Part A2)." }
docker compose exec $WebService nginx -s reload
if ($LASTEXITCODE -ne 0) { Fail "The web server did not reload." "Run:  docker compose restart $WebService" }
docker compose up -d $CertbotService | Out-Null
Ok "certificate installed, web server reloaded, automatic renewal running"

Write-Host ""
docker compose run --rm --entrypoint certbot $CertbotService certificates
Write-Host ""
Write-Host "Done. Open https://$Domain - the padlock should show with no warning." -ForegroundColor Green
Write-Host "(If a browser still warns, close ALL its windows and reopen - it can remember the old certificate.)"
Pop-Location
