# Get ACE live at placewareaiapp.online — step by step

Everything below is click-by-click. Do the steps in order.

**Current state (30 Sep 2026):** DNS ✅ · Windows Firewall ✅ · App running ✅ ·
TP-Link rules ✅ · MikroTik rules ✅. The domain now opens ACE's own web server:
you see "Your connection isn't private" (`NET::ERR_CERT_AUTHORITY_INVALID`).
**What's left is Step 7, the real certificate.**

---

## ⚠️ Read this first — don't lock yourself out

Right now you open the router by typing `placewareaiapp.online/webfig` in a
browser. That works *because* nothing forwards ports 80/443 yet, so the domain
lands on the router itself.

**As soon as you add the rules in Step 3, that stops working.** The domain will
go to the ACE server instead — which is the whole point, but it means you lose
that way into the router.

**Before you change anything, prove you have another way in.** In a browser,
open:

```
http://172.16.0.1
```

- **Router login page appears** → you're safe, carry on to Step 1.
- **Nothing loads** → stop. Don't add the rules yet. Either do this with the
  consultant on Building 1's network, or ask him to confirm how you'll reach
  the router afterwards. Adding the rules without this could leave nobody able
  to log in and undo them.

- [ ] `http://172.16.0.1` opens the router login

---

## Step 1 — Find the TP-Link's WAN IP

The MikroTik needs to know *where* to send the traffic. That address is the
TP-Link's "outside" IP — a number starting `172.16.`

**It is NOT `192.168.0.1`.** That's the TP-Link's inside address and won't work
here.

### Easiest way — on the TP-Link

1. Browser → `http://192.168.0.1` → log in
2. Top menu → **Advanced**
3. Left sidebar → **Status**
4. Find the **Internet** box
5. Read the **IP Address** line — it'll look like `172.16.1.20`

### Or — on the MikroTik

1. Browser → `http://172.16.0.1` → log in
2. Left sidebar → **IP** → **DHCP Server**
3. Click the **Leases** tab
4. Find the row for the TP-Link and read its address

Write it here:

```
TP-Link WAN IP: ________________
```

- [ ] Got the TP-Link WAN IP

---

## Step 2 — Open the NAT rules list on the MikroTik

1. Browser → `http://172.16.0.1` → log in
2. In the **left sidebar**, click **IP** — a submenu opens underneath
3. In that submenu, click **Firewall**
4. Along the top of the main panel, click the **NAT** tab
5. You'll see the existing rules listed — including the `3389` one

Before adding anything, **check nothing already uses ports 80 or 443**: scan
the **Dst. Port** column. You should only see `3389`. If you spot an `80` or
`443`, stop and tell me.

- [ ] NAT list open, no existing 80 or 443 rule

---

## Step 3 — Add the HTTPS rule (port 443)

Still on the **NAT** tab, click **Add New**. A blank rule form opens.

> **If a field has no text box next to it**, click the small triangle (▾) beside
> its name to reveal one.
>
> **Do not tick the little checkbox** next to a field. In MikroTik that means
> "NOT this value" — it would invert the rule and break it.

Fill in **exactly** these, leaving everything else untouched:

| Field | What to do |
|---|---|
| **Enabled** | leave ticked ✅ |
| **Chain** | choose `dstnat` from the dropdown |
| **Src. Address** | leave empty |
| **Dst. Address** | type `102.223.1.15` |
| **Protocol** | choose `6 (tcp)` from the dropdown |
| **Src. Port** | leave empty |
| **Dst. Port** | type `443` |
| **Any. Port** | leave empty |
| **In. Interface** | leave empty |

Now scroll **down** the same form to the **Action** section:

| Field | What to do |
|---|---|
| **Action** | choose `dst-nat` from the dropdown |
| **To Addresses** | type your **TP-Link WAN IP** from Step 1 |
| **To Ports** | type `443` |

Click **OK** at the top to save. The new rule appears in the list.

- [ ] Port 443 rule saved

---

## Step 4 — Add the HTTP rule (port 80)

Click **Add New** again. Identical to Step 3, except the two ports are `80`:

| Field | Value |
|---|---|
| **Chain** | `dstnat` |
| **Dst. Address** | `102.223.1.15` |
| **Protocol** | `6 (tcp)` |
| **Dst. Port** | **`80`** |
| **Action** | `dst-nat` |
| **To Addresses** | *your TP-Link WAN IP* |
| **To Ports** | **`80`** |

Click **OK**.

> **Why port 80 matters even though the app is HTTPS:** Let's Encrypt proves
> you own the domain by contacting port 80. Skip this rule and the certificate
> can never be issued — the browser warning stays permanently.

- [ ] Port 80 rule saved

---

## Step 5 — Confirm the TP-Link rules are still there

1. Browser → `http://192.168.0.1` → log in
2. Top menu → **Advanced**
3. Left sidebar → **NAT Forwarding** → **Port Forwarding**

You should see two enabled entries:

| Device IP | External Port | Internal Port | Protocol |
|---|---|---|---|
| `192.168.0.112` | `443` | `443` | TCP |
| `192.168.0.112` | `80` | `80` | TCP |

If either is missing, click **Add** and create it — Device IP Address is
`192.168.0.112`, Protocol `TCP`, Enable This Entry ticked.

- [ ] Both TP-Link rules present and enabled

---

## Step 6 — Test it

Use a **phone on mobile data**. Office Wi-Fi won't prove anything — it can
reach the server internally and give a false result.

Open:
```
https://placewareaiapp.online
```

**What you should see:** a certificate warning ("Your connection is not
private"). Tap **Advanced** → **Proceed**. Then the **ACE login page**.

**That warning is expected and correct at this stage.** Seeing the ACE login
page behind it means the whole chain works. Step 7 removes the warning.

### If it doesn't work

| What you see | What it means |
|---|---|
| The **router login page** | The MikroTik rules aren't matching. Recheck Steps 3–4 — usually Chain isn't `dstnat`, or To Addresses has the wrong IP. |
| **Times out / won't connect** | Traffic is reaching the MikroTik but dying after. Recheck the TP-Link rules in Step 5. |
| **ACE login page** ✅ | Working. Move to Step 7. |

- [ ] ACE login page loads over mobile data

---

## Step 7 — Get the real certificate (removes the warning)

### Why you see the warning

ACE currently uses a **self-signed certificate**, one it made for itself when it
first started. It encrypts the connection fine, but no browser trusts a
certificate that vouches for itself, so every browser shows *"Your connection
isn't private"* (`NET::ERR_CERT_AUTHORITY_INVALID`).

The fix is a free certificate from **Let's Encrypt**, which every browser
trusts. Before issuing it, Let's Encrypt proves you own `placewareaiapp.online`:
it asks for a small file at `http://placewareaiapp.online/.well-known/acme-challenge/…`
over **port 80**. That's why the port-80 rules in Steps 3–5 matter.

### Which machine? — the ACE server only

| Machine | Do you run this? | Why |
|---|---|---|
| **ACE server** (`192.168.0.112`, the one the domain points to) | **Yes, once** | The certificate must live on the machine that answers `placewareaiapp.online`. |
| **Dev laptop** | **No** | You reach ACE there through `https://localhost`, and no public authority will issue a certificate for "localhost". That local warning is normal and harmless. The same settings are on the laptop, but its certbot just finds nothing to renew and stays idle. |

You don't need Ubuntu / WSL. Everything runs inside Docker, so ignore the
older instruction about the WSL toggle.

### 7a — Get the latest ACE files onto the server

The fix is in two files. The server needs both:

- `backend\docker-compose.yml` (adds the `certbot` service and the Let's Encrypt check folder)
- `deploy\issue-cert.ps1` (the one-click script)

Update the ACE folder on the server the way you normally do (git pull, or copy
those two files over the old ones). No rebuild is needed.

- [ ] Server has the new `docker-compose.yml` and `deploy\issue-cert.ps1`

### 7b — Make sure port 80 really reaches the server from the internet

On a **phone using mobile data** (not office Wi-Fi), open:

```
http://placewareaiapp.online
```

It should jump to `https://…` and show the certificate warning. That means port 80
and port 443 both arrive. If it times out, recheck Steps 3–5 (the port **80** rules).

- [ ] Port 80 works from mobile data

### 7c — Run the certificate script (on the server)

1. On the ACE server, make sure **Docker Desktop** is open and says **Engine running**.
2. Press the **Windows key**, type **PowerShell**, and open **Windows PowerShell**.
3. Go to the ACE folder. Change the path to wherever ACE lives on the server:
   ```powershell
   cd "C:\path\to\Chat Assisant  placeware x1"
   ```
4. Run this, with a real email address that receives expiry warnings (use a
   shared Placeware/IT address rather than a personal one):
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\deploy\issue-cert.ps1 -Email it@placeware.com
   ```
   If `www.placewareaiapp.online` also has a DNS record pointing to the office,
   add `-IncludeWww` at the end so both names are covered.

The script prints five numbered steps. Each should end with a green **OK**:

| Step | What it does |
|---|---|
| 1 | Starts the web server and the certbot helper with the new settings |
| 2 | Checks the web server can serve Let's Encrypt's check file |
| 3 | **Practice run** against Let's Encrypt's test servers. This proves the internet can reach you, without using up real attempts. |
| 4 | Gets the **real** certificate |
| 5 | Installs it where the web server already looks and reloads it. No downtime. |

At the end it lists the certificate and its expiry date (about 90 days away).

- [ ] Script finished with "Done"

### 7d — Check the padlock

1. Close **all** browser windows (browsers remember the old certificate), then reopen.
2. Go to `https://placewareaiapp.online`. You should see the **padlock** and no warning.
3. Check on a phone on mobile data too.

- [ ] Padlock shows, no warning (computer and phone)

### Renewal — nothing to do

Let's Encrypt certificates last **90 days**. The `certbot` container (it shows as
`placeware-certbot` in Docker Desktop) checks **twice a day** and renews
automatically once fewer than 30 days remain. The web server reloads itself
every 6 hours to pick up the new certificate. Keep Docker Desktop set to
**start when Windows starts** (Docker Desktop → Settings → General) so this
keeps running after a reboot.

To see the current certificate and its expiry at any time (on the server, in the ACE `backend` folder):
```powershell
docker compose run --rm --entrypoint certbot certbot certificates
```

### If the script stops with FAILED

| Message | What to do |
|---|---|
| **Docker is not running** | Open Docker Desktop, wait for *Engine running*, run the script again. |
| **Step 2: web server did not return the check file** | Run `docker compose up -d --force-recreate frontend` in the `backend` folder, then run the script again. |
| **Step 3: could not reach this server on port 80** | Port 80 isn't getting in from the internet. Redo 7b and Steps 3–5. Also check Windows Firewall allows **port 80** inbound. |
| **"too many failed authorizations" / "rate limit"** | Let's Encrypt limits repeated attempts. Wait an hour, fix the port-80 issue, try again. The practice run in step 3 is there to avoid this. |
| **Padlock still missing after success** | Close every browser window and reopen. Or try a private/incognito window. |

---

## Then you're live

`https://placewareaiapp.online` — clean address, valid certificate, reachable
from anywhere.

---

## For the consultant — two security items

Neither blocks us. Both should be fixed.

**1. The router's admin page is open to the whole internet.**
That's why WebFig appeared when you visited the domain. On **RouterOS v6.42.11**
(released 2018) that's a real risk. Our port-80 rule hides the symptom, but the
service is still listening.

Fix: **IP → Services** → move `www` off port 80 and `www-ssl` off 443, and set
*Available From* to the local network only. A RouterOS update is also overdue.

**2. Remote Desktop (port 3389) is exposed to the internet.**
The existing rule sends RDP straight from the public IP to `172.16.1.7`.
Internet-facing RDP is among the most common ways ransomware enters a network.
It normally belongs behind a VPN, or at minimum restricted by source IP.

His infrastructure, his call — but worth him knowing, with client data on the
same network.
