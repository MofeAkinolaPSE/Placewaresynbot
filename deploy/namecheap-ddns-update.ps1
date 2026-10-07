# deploy/namecheap-ddns-update.ps1
# ---------------------------------------------------------------------------
# Keeps placewareaiapp.online pointed at this server's CURRENT public IP.
#
# Why this exists: the office connection hands out a dynamic public IP. It was
# observed changing (102.223.1.15 -> 102.89.40.33 -> 102.223.1.15) within a few
# hours. A plain DNS A record would silently stop resolving to this server the
# next time that happens, taking the whole app offline with no warning.
#
# Namecheap's Dynamic DNS endpoint rewrites the A record in place. Called with
# no "ip" parameter, Namecheap uses the IP the request arrives from -- which is
# exactly this server's current public IP, so nothing needs to detect it.
#
# SETUP (one time):
#   1. Namecheap -> Domain List -> Manage -> Advanced DNS
#   2. Scroll to DYNAMIC DNS -> toggle ON
#   3. Copy the "Dynamic DNS Password" it reveals
#   4. Paste it into $Password below, and save this file
#   5. Register the scheduled task (see GO-LIVE-DOMAIN.md Step 4)
#
# Run it manually once after setup to confirm it prints OK for both hosts.
# ---------------------------------------------------------------------------

$Domain   = "placewareaiapp.online"
$Password = "PUT-YOUR-NAMECHEAP-DDNS-PASSWORD-HERE"
$Hosts    = @("@", "www")

$logDir = "C:\placeware-logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$logFile = Join-Path $logDir "ddns-update.log"

foreach ($h in $Hosts) {
    $url = "https://dynamicdns.park-your-domain.com/update?host=$h&domain=$Domain&password=$Password"
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    try {
        $resp = Invoke-RestMethod -Uri $url -TimeoutSec 30
        $r = $resp.'interface-response'
        if ($r.ErrCount -eq "0") {
            $line = "$stamp  OK    host=$h  ip=$($r.IP)"
        } else {
            # Namecheap reports failures in-band with HTTP 200, so the XML body
            # is the only place a wrong password or missing record shows up.
            $line = "$stamp  FAIL  host=$h  $($r.errors.Err1)"
        }
    } catch {
        $line = "$stamp  ERROR host=$h  $($_.Exception.Message)"
    }
    Write-Output $line
    Add-Content -Path $logFile -Value $line
}
