# Placeware — Full Simulation Environment Plan

## Context

Every attempt to install the bridge on the client's Windows 7 server failed due to a chain
of missing Windows updates on an unpatched machine:
- .NET 4.8 installer rejected (error 0x800b0109 — untrusted root certificate)
- Python 3.8.10 socket DLL failure (missing WSA flag support on Win7)
- get-pip.py version mismatch (latest pip dropped Python 3.8 support)
- KB2533623 patch missing (DLL secure loading APIs absent)

The client's server has TWO partitions: C: (Sage installation) and D: (company data +
setup files). All installation files should stay on D: to avoid drive-switching in CMD.

**Goal:** Build a controlled simulation on the dev laptop that mirrors the exact production
topology, diagnose every dependency, and produce a guaranteed installation sequence for
the real Windows 7 server.

**Simulation topology:**
```
Dev Laptop (Windows 11)
├── Docker Desktop
│   └── placeware stack (backend + postgres + nginx) → port 80/443
└── VirtualBox 7.x
    └── Windows 7 SP1 VM  (mirrors the client's server exactly)
        ├── C:\  — Sage 50 2013 installed here (mirrors client C:)
        ├── D:\  — company data + all setup files (mirrors client D:)
        └── sage-bridge running on port 7070
```

---

## Phase 0 — Pre-Download Everything on the Laptop BEFORE Creating the VM

**Critical:** Clean Windows 7 has no internet browser, no curl, no package manager.
All files must be on the laptop first, then transferred into the VM via a VirtualBox
Shared Folder. Do this before Phase 1.

**Create a staging folder on the laptop:**
```
C:\PlacewareSetup\
├── patches\
│   ├── Windows7-KB3020369-x64.msu
│   ├── Windows6.1-KB2533623-x64.msu
│   ├── Windows6.1-KB2999226-x64.msu
│   ├── Windows6.1-KB3118401-x64.msu
│   └── WMF30-Windows6.1-KB2506143-x64.msu
├── NDP472-KB4054530-x86-x64-AllOS-ENU.exe
├── vc_redist.x64.exe
├── python-3.8.6-embed-amd64.zip
├── get-pip.py
├── nssm-2.24.zip
├── curl.exe                            ← needed; Win7 has no built-in curl
└── Sage50_2013_installer.exe
```

**Download each file now (links in the Files to Download section at the bottom).**

Once the VM exists (after Phase 2), configure the shared folder:
- VirtualBox → Settings → Shared Folders → Add → select `C:\PlacewareSetup\`
  → Folder Name: `PlacewareSetup` → check "Auto-mount" → OK.
- Inside the VM after Guest Additions are installed, the share appears as
  `\\VBOXSVR\PlacewareSetup` or as a drive letter in File Explorer.
- Copy the entire contents to `D:\installs\` inside the VM before starting Phase 3.

---

## Phase 1 — Install VirtualBox 7.x on the Laptop

**Why 7.x not 6.1:** The VBoxHardening.log confirmed VirtualBox 6.1 has a
user32.dll hardening bug on Windows 7 HOST machines. We are running Win7 as
a GUEST on a Windows 11 host — VirtualBox 7.x handles this correctly.

1. Download **VirtualBox 7.0.x** platform package for Windows hosts from:
   `https://www.virtualbox.org/wiki/Downloads`
   → Click "Windows hosts" under VirtualBox 7.0.x platform packages.
2. Also download the **VirtualBox 7.0.x Extension Pack** (same page, same version)
   → Click "All supported platforms" under Extension Pack.
3. Install VirtualBox: run the `.exe`, accept defaults, allow the network adapter install.
4. Install Extension Pack: open VirtualBox → Tools → Extensions → Add → select `.vbox-extpack`.

---

## Phase 2 — Create the Windows 7 SP1 VM

**VM Settings (exact values):**

| Setting | Value | Reason |
|---------|-------|--------|
| Name | `Placeware-Win7-Sage` | |
| Type | Microsoft Windows | |
| Version | Windows 7 (64-bit) | |
| RAM | 2048 MB minimum, 4096 MB preferred | Sage 50 + Python needs headroom |
| CPU | 2 cores | |
| Video Memory | 128 MB | |
| Hard Disk | 60 GB, VDI, dynamically allocated | Sage install is ~2 GB; leave room |
| Network Adapter 1 | **Bridged Adapter** → select your laptop's active WiFi/ethernet | VM gets real LAN IP, same subnet as backend Docker |
| Network Adapter 2 | **NAT** | Internet access for downloading patches in VM |

**Why Bridged:** The backend Docker containers are accessed via the laptop's LAN IP.
The bridge in the VM needs to call back to the backend. Bridged networking puts the
VM on the same LAN so both sides use real IPs — closest match to production.

**Create two virtual disks to simulate the D: partition:**
- After creating the VM: Settings → Storage → Add Hard Disk → Create → 20 GB VDI.
- This will be the D: drive inside the VM.

**Install Windows 7:**
1. In VM Settings → Storage → add the Windows 7 SP1 ISO as optical drive.
2. Start VM → boot from ISO → install normally.
3. During partition setup: assign ~40 GB to C: and ~18 GB to the second disk (will become D:).
4. Complete Windows 7 install. Username: `PlacewareServer` (matches client's username).
5. After first boot: open Disk Management → the second disk will show as unallocated →
   right-click → New Simple Volume → format NTFS → assign letter **D:**.

**Install VirtualBox Guest Additions (required for shared folder access):**
- VM menu → Devices → Insert Guest Additions CD → run `VBoxWindowsAdditions.exe` inside VM.
- Restart. This enables proper screen resolution, shared clipboard, and shared folders.

**Transfer all setup files into the VM:**
After Guest Additions are installed, the shared folder `C:\PlacewareSetup\` on the laptop
appears in the VM. Copy everything to `D:\installs\` inside the VM:
```cmd
xcopy \\VBOXSVR\PlacewareSetup\* D:\installs\ /E /Y
```
If the drive letter was assigned (e.g., Z:), use `Z:\` instead of `\\VBOXSVR\PlacewareSetup\`.

---

## Phase 3 — Patch Windows 7 in Exact Order

**This is the sequence that failed in production. Do not skip or reorder.**

All patch files should already be in `D:\installs\patches\` (copied in Phase 2).

| Order | KB Number | Filename | Purpose | Why Required |
|-------|-----------|----------|---------|--------------|
| 1 | KB3020369 | `Windows7-KB3020369-x64.msu` | Servicing Stack Update | Must be installed FIRST — enables all other patches to install |
| 2 | KB2533623 | `Windows6.1-KB2533623-x64.msu` | DLL Secure Loading | Adds `SetDefaultDllDirectories` — without this Python gets "parameter is incorrect" on socket |
| 3 | KB2999226 | `Windows6.1-KB2999226-x64.msu` | Universal CRT | Provides `ucrtbase.dll` and `api-ms-win-crt-*.dll` — fixes the original "missing DLL" error |
| 4 | KB3118401 | `Windows6.1-KB3118401-x64.msu` | VC++ 2015 Prereq | Required before Visual C++ redistributable installs correctly |
| 5 | KB2506143 | `WMF30-Windows6.1-KB2506143-x64.msu` | Windows Management Framework 3.0 | Upgrades PowerShell 2.0 → 3.0, required by install-service.ps1 |

**Install each patch via CMD (run as Administrator):**
```cmd
wusa.exe D:\installs\patches\Windows7-KB3020369-x64.msu /quiet /norestart
shutdown /r /t 0
```
Wait for reboot, reconnect, then install the next one. **Restart after EACH patch.**

After all 5 patches are installed and the VM has rebooted:

```cmd
rem Install Visual C++ 2015-2019 Runtime
D:\installs\vc_redist.x64.exe /quiet /norestart
shutdown /r /t 0
```

---

## Phase 4 — Install .NET Framework 4.7.2

**Why 4.7.2 not 4.8:** The .NET 4.8 installer uses a certificate chain that
Windows 7's unpatched certificate store does not trust (error 0x800b0109, confirmed
in the framework error log). .NET 4.7.2 uses the older chain that Windows 7 trusts.
pythonnet works correctly with .NET 4.7.2.

File should already be in `D:\installs\`. Run:
```cmd
D:\installs\NDP472-KB4054530-x86-x64-AllOS-ENU.exe /quiet /norestart
shutdown /r /t 0
```

**Verify:**
```cmd
reg query "HKLM\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full" /v Release
```
Value `461808` or higher = 4.7.2 installed. ✓

---

## Phase 5 — Install Python 3.8.6 Embeddable

**Why 3.8.6 embeddable:** Python 3.8.10 socket module fails on Windows 7 (uses
`WSA_FLAG_NO_HANDLE_INHERIT` not available until Win8). Python 3.8.6 predates this
change. Embeddable package = no installer, no admin rights complexity, just a zip.

All Python files go to `D:\py38\` (D: drive, matching client's file layout).

**Extract the zip (PowerShell 3.0 is now available after Phase 3 KB2506143):**
```cmd
powershell -Command "Expand-Archive -Path D:\installs\python-3.8.6-embed-amd64.zip -DestinationPath D:\py38\"
```

**Fix the critical embeddable setting:**
```cmd
notepad D:\py38\python38._pth
```
Find `#import site` → remove the `#` → save.

**Install pip (use Python 3.8 specific version):**
```cmd
D:\py38\python.exe D:\installs\get-pip.py
```

**Copy curl.exe to a permanent location:**
```cmd
copy D:\installs\curl.exe C:\Windows\System32\curl.exe
```
This makes `curl` available system-wide in CMD for health checks in later phases.

**Verify:**
```cmd
D:\py38\python.exe --version
D:\py38\python.exe -m pip --version
D:\py38\python.exe -c "import socket; print('socket OK')"
```
All three must succeed before proceeding.

---

## Phase 6 — Install Sage 50 2013 in the VM

Sage 50 installs on **C:** (matching the client's server layout).

1. Copy the Sage 50 2013 installer to `D:\installs\`.
2. Run the Sage installer — accept defaults, install to `C:\Program Files (x86)\Sage\Peachtree\`.
3. Launch Sage 50 after install and create a **sample company** (use the built-in sample company
   or create a new one). Note the exact company folder path that Sage shows in Help → About.
4. The company data `.DAT` files will be in a path like:
   `C:\Users\PlacewareServer\AppData\Roaming\Sage\Peachtree\Company\SampleCompany\`
   or `C:\Sage\Peachtree\Company\SampleCompany\` — note the EXACT path.

**Verify the DLL exists:**
```cmd
dir "C:\Program Files (x86)\Sage\Peachtree\API\Sage.Peachtree.API.dll"
```
Must show the file. If missing, Sage installed incorrectly.

**Verify the ODBC DSN:**
- Press Win+R → type `odbcad32` → System DSN tab.
- Look for a Pervasive/Actian DSN. Note the exact name.
- This name goes into `SAGE_ODBC_DSN` in the bridge `.env`.

---

## Phase 7 — Install the Bridge

Copy the `sage-bridge` folder to `D:\PlacewareBridge\sage-bridge\`.
(Copy from shared folder: `xcopy \\VBOXSVR\PlacewareSetup\sage-bridge D:\PlacewareBridge\sage-bridge\ /E /Y`)

**Install Python packages:**
```cmd
D:\py38\python.exe -m pip install -r D:\PlacewareBridge\sage-bridge\requirements.txt
```

If `pythonnet` install fails:
```cmd
D:\py38\python.exe -m pip install pythonnet==3.0.3 --no-build-isolation
```

---

## Phase 8 — Configure the Bridge .env

```cmd
notepad D:\PlacewareBridge\sage-bridge\.env
```

**Values to set (all others stay as-is):**

```env
BRIDGE_API_KEY=placeware-bridge-dev-key-2026
SAGE_MOCK=false

# Path to Sage DLL (confirm exact path in VM)
SAGE_API_DLL_PATH=C:\Program Files (x86)\Sage\Peachtree\API\Sage.Peachtree.API.dll

# Path to company data folder (get exact path from Sage → Help → About)
SAGE_COMPANY_PATH=<exact path from Sage Help → About>

# DSN name from odbcad32 → System DSN tab
SAGE_ODBC_DSN=<DSN name shown in ODBC admin>

# Laptop's LAN IP (run ipconfig on the laptop, use WiFi/ethernet IPv4)
SYNBOT_WEBHOOK_URL=http://<LAPTOP_LAN_IP>/sage/webhook

SYNBOT_WEBHOOK_KEY=placeware-webhook-secret-2026
BRIDGE_HOST=0.0.0.0
BRIDGE_PORT=7070
BRIDGE_INSECURE_SKIP_VERIFY=true
```

**Note:** Use `http://` (not https) for SYNBOT_WEBHOOK_URL pointing to the laptop
since Docker's nginx is also accessible on port 80 (HTTP redirect) and the self-signed
cert issue is avoided entirely for the simulation.

---

## Phase 9 — Open Windows 7 Firewall for Port 7070

The backend Docker containers need to reach the bridge on port 7070.
Without this, the backend gets connection refused.

```cmd
netsh advfirewall firewall add rule name="Placeware Bridge" dir=in action=allow protocol=TCP localport=7070
```

---

## Phase 10 — Start the Backend (on the Laptop)

On the **laptop** (not in the VM):

```cmd
cd "C:\Users\DELL\Desktop\Moe\Chat Assisant  placeware x1"
docker compose up -d
```

Wait for all services to be healthy:
```cmd
docker compose ps
```
All services should show `healthy` or `running`.

**Update backend `.env` with the VM's IP:**
After the VM boots and gets a LAN IP (check `ipconfig` inside the VM), update
`backend/.env` on the laptop:
```env
SAGE_MOCK=0
SAGE_BRIDGE_URL=http://<VM_LAN_IP>:7070
SAGE_BRIDGE_KEY=placeware-bridge-dev-key-2026
```
Then redeploy: `docker compose up -d --force-recreate backend`

---

## Phase 11 — Start the Bridge and Run Full Test

**In the VM**, open CMD in `D:\PlacewareBridge\sage-bridge\`:

```cmd
cd D:\PlacewareBridge\sage-bridge
D:\py38\python.exe -m uvicorn main:app --host 0.0.0.0 --port 7070
```

Expected startup output:
```
INFO: Sage Bridge starting (MOCK MODE: False)
INFO: Sage SDK loaded.
INFO: Sage company session opened: <path>
INFO: Uvicorn running on http://0.0.0.0:7070
```

**In a second CMD window (still in VM):**
```cmd
D:\py38\python.exe D:\PlacewareBridge\sage-bridge\test_connectivity.py
```

All 6 checks should pass. The critical ones:
- ✓ Bridge liveness
- ✓ API key auth
- ✓ ODBC connected (Pervasive DSN reachable)
- ✓ SDK loaded (Sage.Peachtree.API.dll)
- ✓ VM backend reachable (http://<LAPTOP_LAN_IP>/sage/webhook)
- ✓ Webhook accepted

**Health check from VM CMD (curl.exe installed in Phase 5):**
```cmd
curl http://localhost:7070/health
```
Expected: `{"status":"ok"}`

---

## Phase 12 — Install as Windows Service (Production-Ready)

Once all 6 checks pass, install the bridge as a Windows service so it
auto-starts on boot using NSSM.

**Extract NSSM (already in D:\installs\):**
```cmd
powershell -Command "Expand-Archive -Path D:\installs\nssm-2.24.zip -DestinationPath D:\installs\nssm\"
mkdir C:\Tools\nssm
copy D:\installs\nssm\nssm-2.24\win64\nssm.exe C:\Tools\nssm\nssm.exe
```

**Edit install-service.ps1 before running it:**
```cmd
notepad D:\PlacewareBridge\sage-bridge\install-service.ps1
```
Change these two lines:
- `$PythonExe` → `D:\py38\python.exe`
- `$BridgeDir` → `D:\PlacewareBridge\sage-bridge`

**Run the service installer:**
```cmd
rem Run as Administrator
powershell -ExecutionPolicy Bypass -File D:\PlacewareBridge\sage-bridge\install-service.ps1
```

**Verify service running:**
```cmd
sc query PlacewareSageBridge
curl http://localhost:7070/health
```

---

## Files to Download (Complete List with Direct Links)

| File | Direct Download | Save As |
|------|----------------|---------|
| VirtualBox 7.0.x installer | Go to `https://www.virtualbox.org/wiki/Downloads` → click **Windows hosts** under 7.0.x | `VirtualBox-7.0.x-Win.exe` |
| VirtualBox 7.0.x Extension Pack | Same page → **All supported platforms** under Extension Pack (same version!) | `Oracle_VM_VirtualBox_Extension_Pack-7.0.x.vbox-extpack` |
| Windows 7 SP1 x64 ISO | Must source separately — requires valid license key (VLSC / retail / OEM). **This is the only item with no free download link.** | `Win7_SP1_x64.iso` |
| `Windows7-KB3020369-x64.msu` | `https://www.catalog.update.microsoft.com/Search.aspx?q=KB3020369` → select **Windows 7 x64** row → Download | `Windows7-KB3020369-x64.msu` |
| `Windows6.1-KB2533623-x64.msu` | `https://www.catalog.update.microsoft.com/Search.aspx?q=KB2533623` → select **Windows 7 for x64-based** row → Download | `Windows6.1-KB2533623-x64.msu` |
| `Windows6.1-KB2999226-x64.msu` | `https://www.catalog.update.microsoft.com/Search.aspx?q=KB2999226` → select **Windows 7 for x64-based** row → Download | `Windows6.1-KB2999226-x64.msu` |
| `Windows6.1-KB3118401-x64.msu` | `https://www.catalog.update.microsoft.com/Search.aspx?q=KB3118401` → select **Windows 7 for x64-based** row → Download | `Windows6.1-KB3118401-x64.msu` |
| `WMF30-Windows6.1-KB2506143-x64.msu` | `https://www.catalog.update.microsoft.com/Search.aspx?q=KB2506143` → select **Windows 7 for x64-based** row → Download | `WMF30-Windows6.1-KB2506143-x64.msu` |
| `vc_redist.x64.exe` | `https://aka.ms/vs/17/release/vc_redist.x64.exe` (direct download, Microsoft-maintained link) | `vc_redist.x64.exe` |
| `NDP472-KB4054530-x86-x64-AllOS-ENU.exe` | `https://dotnet.microsoft.com/en-us/download/dotnet-framework/net472` → click **Download .NET Framework 4.7.2 Runtime** → select offline installer | `NDP472-KB4054530-x86-x64-AllOS-ENU.exe` |
| `python-3.8.6-embed-amd64.zip` | `https://www.python.org/ftp/python/3.8.6/python-3.8.6-embed-amd64.zip` (direct download) | `python-3.8.6-embed-amd64.zip` |
| `get-pip.py` (3.8 version) | `https://bootstrap.pypa.io/pip/3.8/get-pip.py` (direct download) | `get-pip.py` |
| `curl.exe` for Windows 7 | `https://curl.se/windows/` → download latest Win64 zip → extract `curl.exe` from the `bin\` folder | `curl.exe` |
| `nssm-2.24.zip` | `https://nssm.cc/release/nssm-2.24.zip` (direct download) | `nssm-2.24.zip` |
| Sage 50 2013 installer | Already available — copy to `C:\PlacewareSetup\` staging area | `Sage50_2013.exe` |

**Note on Microsoft Update Catalog downloads:** The catalog site requires Internet Explorer
or Edge (it uses an ActiveX download control). Use Edge on the laptop to download the `.msu`
files. Click the KB link, then click the file name to get the direct download popup.

---

## Critical .env Changes Reference

### sage-bridge/.env (inside VM)
```
SAGE_MOCK=false
SAGE_API_DLL_PATH=C:\Program Files (x86)\Sage\Peachtree\API\Sage.Peachtree.API.dll
SAGE_COMPANY_PATH=<from Help → About in Sage>
SAGE_ODBC_DSN=<from odbcad32 System DSN tab>
SYNBOT_WEBHOOK_URL=http://<laptop LAN IP>/sage/webhook
BRIDGE_INSECURE_SKIP_VERIFY=true
```

### backend/.env (on laptop)
```
SAGE_MOCK=0
SAGE_BRIDGE_URL=http://<VM LAN IP>:7070
SAGE_BRIDGE_KEY=placeware-bridge-dev-key-2026
```

### install-service.ps1 (two-line change)
```
$PythonExe → D:\py38\python.exe
$BridgeDir → D:\PlacewareBridge\sage-bridge
```

---

## Verification — End-to-End Test

1. VM booted, bridge service running (`sc query PlacewareSageBridge` → RUNNING)
2. Docker backend running (`docker compose ps` → all healthy)
3. From VM CMD: `curl http://localhost:7070/health` → `{"status":"ok"}`
4. From laptop CMD: `curl http://<VM_LAN_IP>:7070/health` → `{"status":"ok"}`
5. From VM CMD: `D:\py38\python.exe test_connectivity.py` → 0 failures
6. From laptop browser: open SynBot UI → ask a question about customers/inventory →
   response pulls real Sage data from the VM bridge
