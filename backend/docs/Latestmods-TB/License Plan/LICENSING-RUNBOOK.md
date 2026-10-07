# Placeware Licensing: Step-by-Step Guide

You do every step on **your own PC**, in **PowerShell inside VS Code**. Only step 6 touches the client server, and all it does there is copy one file.

---

## Before you start: open the right terminal

1. Open the project folder in VS Code (the one you already use).
2. Open a terminal: menu **Terminal → New Terminal** (or press <kbd>Ctrl</kbd> + <kbd>`</kbd>).
3. Check that the dropdown at the top-right of the terminal panel says **powershell**. If it doesn't, click the **⌄** next to **+** and choose **PowerShell**.
4. Go to the project root. Copy and paste this exactly, quotes included (the folder name has **two spaces** in it):
   ```powershell
   cd "C:\Users\DELL\Desktop\Moe\Chat Assisant  placeware x1"
   ```
5. Check that Python is ready:
   ```powershell
   python -c "import cryptography; print('ready')"
   ```
   - If it prints `ready`, carry on.
   - If you see `No module named cryptography`, run `pip install cryptography` and try again.

> **Every command in this guide is run from that folder, in that terminal.**

---

## Step 1: Create your private key (once, ever)

```powershell
python tools/licensing/neurolayer_license.py keygen --install
```

It asks for a passphrase:

```
Signing-key passphrase:
Repeat passphrase:
```

- **Nothing appears on screen while you type.** That's normal, the same as typing a password on a server. Type it and press Enter.
- Use at least 12 characters. **This passphrase is your "encryption key"**: you'll type it every time you issue a licence. Save it in your password manager.

When it finishes you'll see something like:

```
Private key (keep secret, back it up): C:\Users\DELL\.neurolayer\licensing\neurolayer_license_signing_key.pem
Public key: E636AAa71TdIkX...
Installed public key into backend\src\licensing\public_key.py - rebuild the backend image once.
```

**Back up the key file now.** Open File Explorer, paste `%USERPROFILE%\.neurolayer\licensing` into the address bar, and copy `neurolayer_license_signing_key.pem` somewhere safe (an encrypted USB stick or your password manager's file storage).

- If you lose that file, you can't issue licences anymore.
- If someone else gets it *and* your passphrase, they can make licences.
- Never put it in the project folder, git, email or WhatsApp. (The tool refuses to save it inside the project anyway.)

> Run `keygen` only **once**. Running it again gives you a new key, and every licence you've already issued stops working after the next build. The tool blocks this unless you add `--force`.

---

## Step 2: Practise on your own PC first

### 2a. Give your PC a licence

```powershell
python tools/licensing/neurolayer_license.py issue --client "Local Test" --license-id TEST-001 --months 1 --install-local
```

- Type your passphrase when asked.
- `--install-local` writes the file straight into `backend\.license\system.dat`, the spot your local backend reads.

### 2b. Rebuild and start the backend

```powershell
cd backend
docker compose up -d --build backend
cd ..
```

This takes a few minutes. Docker Desktop must be running.

### 2c. Check it

Open this in your browser: **http://localhost:8000/license/status**

You should see `"state": "valid"` and an `expires_on` date one month from today.

### 2d. See the lock work

Issue a licence that already ran out (August, plus 7 days of grace):

```powershell
python tools/licensing/neurolayer_license.py issue --client "Local Test" --license-id TEST-002 --start 2026-08-01 --months 1 --install-local
```

Wait about 30 seconds, then refresh the status page. It should show `"state": "expired"` and `"locked": true`. The app UI now shows the **Subscription expired** screen. Your data is untouched.

### 2e. Unlock again

Re-run the 2a command with `--license-id TEST-003`. Within about 30 seconds the app works normally again. **No restart needed.**

---

## Step 3: Commit and deploy the build that contains your public key

Step 1 changed one code file, `backend/src/licensing/public_key.py`. It holds only the public half of the key, so it's safe to commit. Commit it with the rest of the licensing code.

> ⚠️ **Order matters.** Before the client server runs this new build, put a licence file on it (step 5 and step 6). Otherwise the app locks with "No licence installed" as soon as it starts.

---

## Step 4: Issue the client's real licence

```powershell
python tools/licensing/neurolayer_license.py issue --client "Placeware Ltd" --license-id PW-001 --start 2026-10-05 --months 1
```

| Part | Meaning |
|---|---|
| `--client "Placeware Ltd"` | Name shown on their lock screen |
| `--license-id PW-001` | Your own reference. Use a new one each time: PW-002, PW-003… |
| `--start 2026-10-05` | First day of the period. Leave it out to mean "today". |
| `--months 1` | Length. The expiry date is worked out for you. |

Extras you can add:

| Option | Effect |
|---|---|
| `--grace 0` | No grace days; locks right at expiry (default is 7) |
| `--lock-mode read_only` | After expiry they can still view, but can't change anything |
| `--support "NeuroLayer - 0803 000 0000"` | Contact shown on the lock screen |

The output tells you where the file went, for example:

```
File: C:\Users\DELL\.neurolayer\licensing\issued\PW-001_2026-10-05\system.dat
```

To double-check any licence file before sending it:

```powershell
python tools/licensing/neurolayer_license.py inspect "C:\Users\DELL\.neurolayer\licensing\issued\PW-001_2026-10-05\system.dat"
```

---

## Step 5: Put the file on the client server

The file always ends up named `system.dat`, in this folder on the server:

| How the server runs | Folder on the server |
|---|---|
| docker compose (`start-stack.sh`) | `<project folder>/backend/.license/` |
| docker swarm (GitHub Actions deploy) | `/var/lib/docker/volumes/placeware_license/_data/` |

### Option A: copy from your PowerShell with `scp`

Run this in the same VS Code PowerShell terminal. Replace `user`, `server-ip` and the project path with the real ones:

```powershell
scp "C:\Users\DELL\.neurolayer\licensing\issued\PW-001_2026-10-05\system.dat" user@server-ip:/home/user/placeware/backend/.license/system.dat
```

The first time, it asks you to confirm the server (type `yes`) and then asks for the server password.

If it says the folder doesn't exist, log in once and create it:

```powershell
ssh user@server-ip
mkdir -p /home/user/placeware/backend/.license
exit
```

Then run the `scp` command again.

**Swarm servers:** that folder needs admin rights. Copy the file to your home folder first, then move it:

```powershell
scp "C:\...\system.dat" user@server-ip:~/system.dat
ssh user@server-ip
sudo mv ~/system.dat /var/lib/docker/volumes/placeware_license/_data/system.dat
exit
```

### Option B: whatever you already use

WinSCP, FileZilla, or the server's file manager all work. Just put `system.dat` in the folder from the table above.

---

## Step 6: Confirm it worked

In your browser, go to **https://\<client-domain-or-ip\>/license/status**

You should see `"state": "valid"` and the new `expires_on`. It updates within about 30 seconds of copying the file, with no restart.

---

## Every month (or every renewal)

1. Open the VS Code PowerShell terminal and run the `cd` command from "Before you start".
2. Run the step 4 `issue` command with:
   - a **new** `--license-id`
   - `--start` set to the old expiry date
3. Copy the new `system.dat` over the old one (step 5).
4. Check the status page (step 6).

Renewing a few days early is fine. A licence counts from the moment you issue it, so there's no gap.

---

## What the client sees

| Status | What happens |
|---|---|
| `valid` | Everything works normally |
| `grace` | Everything works; an amber banner says the subscription expired and gives the days left |
| `expired` | **Locked**: "Subscription expired" screen, and the API refuses requests |
| `missing` | **Locked**: no `system.dat` on the server |
| `invalid` | **Locked**: the file was edited, or it's signed with a different key |
| `clock_rollback` | **Locked**: someone moved the server clock backwards |
| `unconfigured` | Works; this build has no public key yet (step 1 not done) |

Their data is never deleted, encrypted or changed by any of this.

---

## If something goes wrong

| Problem | Fix |
|---|---|
| `python` is not recognised | Use the VS Code terminal (it uses the project's Python), or install Python from python.org |
| `No module named cryptography` | `pip install cryptography` |
| `Wrong passphrase` | Retype it; check Caps Lock |
| `No signing key at ...` | Step 1 hasn't been done on this PC, or the key file was moved. Restore it from your backup into `%USERPROFILE%\.neurolayer\licensing\` |
| `WARNING: this key does not match ... public_key.py` | You're signing with a different key than the one built into the app. Use your original key file. |
| Status shows `invalid` | Run `inspect` on the file. Usually it was edited, or signed with the wrong key. |
| Status shows `clock_rollback` | Fix the server's clock, then issue and install a **new** licence. A newer licence clears the lock. |
| Status page won't load | Make sure the backend was rebuilt with this code. On the server, `docker logs chat-backend.v1` shows `Licence state: ...` lines. |

---

## For developers: where the code lives

- `backend/src/licensing/`
  - `license_format.py`: signing and checking
  - `license_manager.py`: works out the status and detects clock rollback
  - `license_guard.py`: the backend lock and `/license/status`
  - `public_key.py`
- `backend/migrations/128_license_state.sql`: one-row table holding the latest time seen (for clock-rollback detection)
- `tools/licensing/neurolayer_license.py`: your issuing tool. It's outside the Docker build, so it never ships to clients.
- `SynbotUI/client/lib/license.ts` and `components/LicenseGate.tsx`: the lock screen and banner
- `backend/tests/test_licensing.py`
