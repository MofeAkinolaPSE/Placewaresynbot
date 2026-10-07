# Get `<DOMAIN>` live with HTTPS: step by step (reusable kit)

This is the **same walkthrough we followed for Placeware** (`placewareaiapp.online`, see
`GO-LIVE-DOMAIN.md` at the repo root), rewritten so it can be reused for another client, such
as RoyanHealth. The steps run in the same order, with the same screens and the same checks.

Do the steps **in order** and tick each box as you go. Every command says **which machine**
and **which program** to run it in.

**What you end up with:** `https://<DOMAIN>` opens the app from anywhere, with a padlock and no
"Your connection isn't private" warning. The certificate is a free one from Let's Encrypt and
renews itself. You never need to visit the Let's Encrypt website; the script talks to it for you.

---

## Progress tracker (update as you go)

| Stage | Status |
|---|---|
| 0. Values filled in, public IP decided | ☐ |
| 1. DNS points at the public IP | ☐ |
| 2. Code changes deployed on the server | ☐ |
| 3. Windows Firewall open | ☐ |
| 4. Router rules (outer router, then inner router) | ☐ |
| 5. App reachable from mobile data (with the warning) | ☐ |
| 6. Real certificate issued, padlock showing | ☐ |

What you'll see along the way (it's what happened with Placeware):

| What `https://<DOMAIN>` shows | Where you are |
|---|---|
| Nothing / timeout | DNS not set yet, or nothing forwards the ports yet |
| **The router's login page (WebFig)** | DNS is working, but the router keeps the traffic for itself. The forwarding rules (Stage 4) aren't there yet. |
| "Your connection isn't private" → Proceed → **the app's login** | Network done ✅. Only the certificate (Stage 6) is left. |
| Padlock, no warning | Live ✅ |

---

## Stage 0: Fill this in first

Replace every `<...>` in this file with the client's values. When you're done, search the file
for `<` to check nothing was missed.

| Placeholder | Meaning | Placeware value | This client |
|---|---|---|---|
| `<DOMAIN>` | the address people type | `placewareaiapp.online` | |
| `<PUBLIC_IP>` | the internet IP **this app** uses (see 0b) | `102.223.1.15` | |
| `<OUTER_ROUTER_IP>` | inside address of the router connected to the internet line (the MikroTik) | `172.16.0.1` | |
| `<INNER_ROUTER_IP>` | inside address of the second router, if there is one (the TP-Link) | `192.168.0.1` | |
| `<INNER_ROUTER_WAN_IP>` | the second router's "outside" address, on the MikroTik network (found in Stage 4, Step 1) | `172.16.x.x` | |
| `<SERVER_LAN_IP>` | the app server's address on its network | `192.168.0.112` | |
| `<APP_FOLDER>` | where the project lives **on the server** | `C:\...\Chat Assisant  placeware x1` | |
| `<COMPOSE_DIR>` | folder (inside `<APP_FOLDER>`) holding `docker-compose.yml` | `backend` | |
| `<WEB_SERVICE>` | compose service running nginx | `frontend` | |
| `<NGINX_CONF>` | the nginx config file, path inside `<APP_FOLDER>` | `SynbotUI\nginx.conf` | |
| `<CERT_DIR>` | folder nginx reads the certificate from (inside the container) | `/etc/ssl/placeware` | |
| `<PREFIX>` | short name for Docker volumes and containers | `placeware` | |
| `<EMAIL>` | shared IT address for expiry warnings (not a personal one) | `it@placeware.com` | |

### 0a. Find the app's own names (from its project files)

On your PC, open the client's project in **VS Code**, then open `<COMPOSE_DIR>\docker-compose.yml`:

- **`<WEB_SERVICE>`**: under `services:`, find the service that runs nginx. Its `image:` mentions
  `nginx`, or it publishes port `80`/`443`, or it's named something like `frontend`, `nginx` or `web`.
  Note its name (the line ending in `:` two spaces in from `services:`).
- **`<NGINX_CONF>`**: in that service, look for a line containing `nginx.conf`:
  - Under `volumes:` (e.g. `- ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf`): the file is
    **mounted**. Changing it later needs only a container restart.
  - Not in compose? The service has `build:`, so the config is **baked into the image**. Find
    the Dockerfile in its `build:` folder and look for a line `COPY ... nginx.conf ...`. Changing
    it later needs a rebuild.
- **`<CERT_DIR>`**: in `<NGINX_CONF>`, find `ssl_certificate`. The folder in that path is
  `<CERT_DIR>`. If nginx doesn't use HTTPS yet, use `/etc/ssl/<PREFIX>`.

Write down whether nginx.conf is **mounted** or **baked in**. Stage 2 needs it.

### 0b. Which public IP will this app use? (read this before anything else)

A public IP can send port 80 and port 443 to **only one** machine. Placeware already uses
80/443 on `102.223.1.15`. Pick the row that matches the new app:

| Situation | What to do |
|---|---|
| **Different building or internet line** from Placeware | Use that line's public IP as `<PUBLIC_IP>`. Follow the guide normally. |
| **Same office and internet line** as Placeware, **different server** | You need a **new public IP** from the ISP. Do **0c** first, then follow the guide with the new IP as `<PUBLIC_IP>`. |
| **Same server** as Placeware | Stop here. Two apps can't both take ports 80/443 on one machine; they need one shared nginx in front of both. That's a design change, so plan it with me first. |

To see what an IP is currently used for: open `http://<the IP>` in a browser, or ask the
consultant which NAT rules reference it (Stage 4, Step 2 shows where they're listed).

### 0c. Add a new public IP to the MikroTik (only if 0b said so)

**Who:** you plus the consultant (he may want to do it himself). The ISP must be involved first.

1. **Ask the ISP** for an additional static public IP for the site. Write down exactly what they give:
   ```
   New public IP: ________________   Prefix / subnet mask: ____ (e.g. /29 or 255.255.255.248)
   ```
   Ask them to confirm the IP is **routed to the site's existing connection**. Without that,
   nothing below will work.
2. On a PC on the office network, open a browser → `http://<OUTER_ROUTER_IP>` → log in.
3. Left sidebar → **IP** → **Addresses**. Find the row with Placeware's IP (`102.223.1.15/...`)
   and note its **Interface** column (e.g. `ether1`). That's the internet-facing port.
4. Click **Add New** and fill in:

   | Field | What to do |
   |---|---|
   | **Enabled** | leave ticked ✅ |
   | **Address** | `<new IP>/<prefix>` exactly as the ISP gave it, e.g. `102.223.1.16/29` |
   | **Network** | leave empty (MikroTik fills it in) |
   | **Interface** | the same interface as Placeware's IP, from step 3 |

5. Click **OK**. The new address appears in the list.
6. **Test:** on a phone on **mobile data**, open `http://<new IP>`. You should see the **MikroTik
   login page**, the same symptom Placeware had at first. That proves the IP reaches the router.
   (Stage 4 then points it at the app server.)

- [ ] New public IP live on the MikroTik (`http://<new IP>` shows the router page from mobile data)

---

## ⚠️ Read this before Stage 4: don't lock yourself out

Same warning as Placeware. If you open the router by typing `<DOMAIN>/webfig` or
`http://<PUBLIC_IP>`, that only works **because** nothing forwards ports 80/443 yet. The traffic
lands on the router itself. **Once you add the Stage 4 rules, that way in is gone**, because the
traffic goes to the app server instead.

**Before changing anything, prove you have another way in.** On a PC on the office network, open:

```
http://<OUTER_ROUTER_IP>
```

- **Router login page appears**: you're safe; carry on.
- **Nothing loads**: stop. Don't add the rules. Do it with the consultant on the office network,
  or have him confirm how you'll reach the router afterwards. Otherwise nobody may be able to log
  in and undo the rules.

- [ ] `http://<OUTER_ROUTER_IP>` opens the router login

---

## Stage 1: DNS (point the domain at the public IP)

**Where:** the domain registrar's website (Namecheap, etc.), in any browser.

1. Log in → **Domain List** → click **Manage** next to `<DOMAIN>` → **Advanced DNS** tab.
2. Under **Host Records**, click **Add New Record**:

   | Type | Host | Value | TTL |
   |---|---|---|---|
   | `A Record` | `@` | `<PUBLIC_IP>` | Automatic |

   Want `www.<DOMAIN>` too? Add a second one: Type `A Record`, Host `www`, Value `<PUBLIC_IP>`.
3. Delete any old **A**, **CNAME** or **URL Redirect** record that also uses Host `@` (e.g.
   Namecheap's default "parking page"). Two records for the same host fight each other.
4. Click the green ✔ to save.

**Check it (on any PC: Windows key → type `PowerShell` → open it):**

```powershell
nslookup <DOMAIN> 8.8.8.8
```

The `Address:` under **Non-authoritative answer** should be `<PUBLIC_IP>`. A new record can take
from a few minutes up to a few hours to show. Run the command again later if it doesn't match yet.

- [ ] `nslookup` returns `<PUBLIC_IP>`

---

## Stage 2: Code changes (in the project, deployed to the server)

Five pieces. Together they mean nginx **never** needs another config change: it always reads the
same two certificate files, and those files are simply replaced (first a self-signed pair, then
the real one, then each renewal).

**Where you do this:** in **VS Code on your PC**, in the client's project. Then get the changed
files onto the server the way you normally deploy (git pull on the server, or copy the files over).

**Skip any piece the project already has.** Search the file for the service or volume name first
(<kbd>Ctrl</kbd>+<kbd>F</kbd>).

> **Indentation matters in `.yml` files.** Use spaces, never tabs. Service names sit **2 spaces**
> in from the left, their settings 4 spaces. Copy the blocks below exactly as shown.

### 2.1 Volumes: in `<COMPOSE_DIR>\docker-compose.yml`, at the very bottom

Scroll to the end of the file. Look for a line `volumes:` that starts at the **left edge** (no
spaces before it). That's the top-level volumes list, not one inside a service.

- **It exists:** paste these entries **under it**, indented 2 spaces like the entries already there.
- **It doesn't:** paste the whole block, including the `volumes:` line, at the end of the file.

```yaml
volumes:
  ssl_certs:            # the two files nginx reads (self-signed first, then the real one)
    name: <PREFIX>_ssl_certs
  letsencrypt:          # Let's Encrypt account + real certificates + renewal settings (never delete)
    name: <PREFIX>_letsencrypt
  certbot_www:          # the domain-check tokens: certbot writes, nginx serves
    name: <PREFIX>_certbot_www
```

### 2.2 Two new services: same file, inside `services:`

Find the line `services:` near the top. Paste both blocks **directly under it**, so they start
2 spaces in, at the same depth as the existing services such as `<WEB_SERVICE>:`.

**`certs-init`** makes a temporary self-signed certificate on first start, so nginx can start
before the real one exists. It skips itself if a certificate is already there.

```yaml
  certs-init:
    image: alpine:3.19
    container_name: <PREFIX>-certs-init
    volumes:
      - ssl_certs:<CERT_DIR>
    command:
      - /bin/sh
      - -c
      - |
        set -e
        if [ ! -f <CERT_DIR>/cert.pem ]; then
          apk add --no-cache openssl
          openssl req -x509 -nodes -newkey rsa:2048 \
            -keyout <CERT_DIR>/key.pem -out <CERT_DIR>/cert.pem -days 825 \
            -subj '/CN=<PREFIX>-internal' -addext 'subjectAltName=IP:127.0.0.1,DNS:localhost'
          chmod 640 <CERT_DIR>/key.pem; chmod 644 <CERT_DIR>/cert.pem
        fi
    restart: "no"
```

**`certbot`** checks twice a day and renews when fewer than 30 days remain. After renewing, it
copies the new files over the two files nginx reads.

```yaml
  certbot:
    image: certbot/certbot:v2.11.0
    container_name: <PREFIX>-certbot
    volumes:
      - letsencrypt:/etc/letsencrypt
      - certbot_www:/var/www/certbot
      - ssl_certs:<CERT_DIR>
    entrypoint:
      - /bin/sh
      - -c
      - |
        trap exit TERM
        while :; do
          certbot renew --quiet --webroot -w /var/www/certbot \
            --deploy-hook 'cp -L "$$RENEWED_LINEAGE/fullchain.pem" <CERT_DIR>/cert.pem && cp -L "$$RENEWED_LINEAGE/privkey.pem" <CERT_DIR>/key.pem && chmod 644 <CERT_DIR>/cert.pem && chmod 640 <CERT_DIR>/key.pem'
          sleep 12h & wait $$!
        done
    restart: unless-stopped
```

`$$` is intentional; it's how docker-compose writes a literal `$`. Don't change it to a single `$`.

### 2.3 The nginx service: same file, inside the existing `<WEB_SERVICE>:` block

Find `  <WEB_SERVICE>:` and add these settings inside it (4 spaces in). **If the service already
has `ports:`, `volumes:`, `command:` or `depends_on:`, add the lines under the existing key.
Never write the same key twice** in one service; the second copy silently replaces the first.

```yaml
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ssl_certs:<CERT_DIR>:ro
      - certbot_www:/var/www/certbot:ro
    # reload every 6h so a renewed certificate is picked up without a restart
    command: ["/bin/sh", "-c", "while :; do sleep 6h; nginx -s reload; done & exec nginx -g 'daemon off;'"]
    depends_on:
      certs-init:
        condition: service_completed_successfully
```

Notes:
- If it already maps ports to something else (e.g. `"8080:80"`), change them to `"80:80"` and
  `"443:443"`. Let's Encrypt only ever knocks on port 80.
- If nginx is the **official image** with a `command:` of its own, replace it with the line above.
  If it has no `command:`, add the line above.

### 2.4 The nginx config: in `<NGINX_CONF>`

Open `<NGINX_CONF>` in VS Code. You need **two `server { ... }` blocks**: one for port 80 and one
for port 443.

**The port-80 block.** Find the `server {` block containing `listen 80;`.
- **It exists:** add the `location /.well-known/acme-challenge/` block **inside it, above** any
  other `location` or `return 301` line. If the block has a bare `return 301 ...;` directly under
  `server_name` (not inside a `location`), move it into `location / { ... }` as shown below.
  Otherwise it redirects the check file too, and the certificate fails.
- **It doesn't exist:** paste the whole block at the top of the file.

```nginx
server {
    listen 80;
    server_name _;

    # Let's Encrypt domain check - must NOT be redirected
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
        try_files $uri =404;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}
```

**The port-443 block.** Find the `server {` block containing `listen 443`. Make sure these lines
are in it, pointing at exactly these two files. Leave all its existing `location` blocks (the
app, `/api`, etc.) as they are.

```nginx
server {
    listen 443 ssl;
    server_name _;
    ssl_certificate     <CERT_DIR>/cert.pem;
    ssl_certificate_key <CERT_DIR>/key.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    # ... the app's existing locations stay here unchanged
}
```

If the app only had a port-80 block with all the app's `location`s in it, change that block to
`listen 443 ssl;` and add the three `ssl_` lines. Then paste the port-80 block above as a new block.

### 2.5 The script: copy it into the project

Copy `deploy\cert-kit\issue-cert.ps1` from the Placeware repo into the client project's
`deploy\` folder (create the folder if needed). Final location: `<APP_FOLDER>\deploy\issue-cert.ps1`.

### 2.6 Deploy and check (on the server)

**Where:** on the **server**, in **Windows PowerShell** (Windows key → type `PowerShell` → open
it). Docker Desktop must be open and showing **Engine running**.

1. Get the changed files onto the server (git pull, or copy them over).
2. Go to the compose folder:
   ```powershell
   cd "<APP_FOLDER>\<COMPOSE_DIR>"
   ```
3. Start everything. Use the line that matches what you found in 0a:
   - nginx.conf **baked in**: rebuild the web image first:
     ```powershell
     docker compose build <WEB_SERVICE>
     docker compose up -d
     ```
   - nginx.conf **mounted**:
     ```powershell
     docker compose up -d --force-recreate <WEB_SERVICE>
     docker compose up -d
     ```
4. **Check nginx serves the check folder.** Run this on the server:
   ```powershell
   curl.exe -s -o NUL -w "%{http_code}`n" http://localhost/.well-known/acme-challenge/test
   ```

   | Result | Meaning |
   |---|---|
   | `404` | ✅ Correct: the check folder is wired up (the test file just doesn't exist) |
   | `301` | ❌ Port 80 redirects it. Fix the order in 2.4, then redo step 3. |
   | `000` / error | ❌ nginx isn't listening on 80. Run `docker compose ps` and check `<WEB_SERVICE>` is "running" with `0.0.0.0:80->80`. |

5. Open `https://localhost` in a browser on the server. The app should load (with a certificate
   warning, which is expected at this stage).

- [ ] Code deployed, `acme-challenge` check returns `404`, app loads on `https://localhost`

---

## Stage 3: Windows Firewall on the server

**Where:** on the **server**, in an **admin** PowerShell. Windows key → type `PowerShell` →
**right-click** it → **Run as administrator** → **Yes**.

Check whether rules already exist:

```powershell
Get-NetFirewallRule -Direction Inbound -Enabled True | Get-NetFirewallPortFilter | Where-Object { $_.LocalPort -in 80,443 }
```

If that prints nothing for port 80 or for 443, add the missing one(s):

```powershell
New-NetFirewallRule -DisplayName "HTTP 80"   -Direction Inbound -Protocol TCP -LocalPort 80  -Action Allow
New-NetFirewallRule -DisplayName "HTTPS 443" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
```

*(Linux server instead: `sudo ufw allow 80,443/tcp`.)*

- [ ] Firewall allows inbound 80 and 443

---

## Stage 4: Router rules (send the internet traffic to the server)

How the traffic travels (Placeware's layout; the client's may have only one router):

```
Internet ──> <PUBLIC_IP> ──> OUTER router (MikroTik, <OUTER_ROUTER_IP>)
                                │  NAT rule: forward to the inner router's outside address
                                ▼
                       INNER router (TP-Link, outside = <INNER_ROUTER_WAN_IP>, inside = <INNER_ROUTER_IP>)
                                │  Port forward: to the server
                                ▼
                       App server <SERVER_LAN_IP>  (nginx on 80 and 443)
```

**Which case are you?** Pick one; it changes Steps 3–5 slightly.

| Case | How to tell | What changes |
|---|---|---|
| **A: one router** | The server's IP is on the MikroTik's own network (starts like `<OUTER_ROUTER_IP>`, e.g. `172.16.…`) | Skip Step 1 and Step 5. In Steps 3–4, **To Addresses** = `<SERVER_LAN_IP>`. |
| **B: two routers, inner router free** | The server is behind a TP-Link that **isn't** already forwarding 80/443 to another machine | Follow every step as written (same as Placeware). |
| **C: two routers, inner router already used** | The server is behind the **same TP-Link that already sends 80/443 to Placeware** (`192.168.0.112`) | That TP-Link can't send 80/443 to two machines. Use **relay ports**: in Steps 3–4 set **To Ports** to `8443` / `8080`. In Step 5, forward External `8443`→Internal `443` and External `8080`→Internal `80`. Visitors still use the normal `https://<DOMAIN>`; the relay ports are only used between the two routers. |

### Step 1: Find the inner router's WAN IP (Cases B and C)

The MikroTik needs to know *where* to send the traffic: the inner router's "outside" IP, a number
starting like `<OUTER_ROUTER_IP>` (e.g. `172.16.`).

**It is NOT `<INNER_ROUTER_IP>`.** That's the inner router's inside address and won't work here.

**Easiest: on the TP-Link**

1. Browser → `http://<INNER_ROUTER_IP>` → log in
2. Top menu → **Advanced**
3. Left sidebar → **Status**
4. Find the **Internet** box
5. Read the **IP Address** line. It'll look like `172.16.1.20`.

**Or: on the MikroTik**

1. Browser → `http://<OUTER_ROUTER_IP>` → log in
2. Left sidebar → **IP** → **DHCP Server**
3. Click the **Leases** tab
4. Find the row for the TP-Link and read its address

Write it here:

```
Inner router WAN IP (<INNER_ROUTER_WAN_IP>): ________________
```

- [ ] Got the inner router's WAN IP

### Step 2: Open the NAT rules list on the MikroTik

1. Browser → `http://<OUTER_ROUTER_IP>` → log in
2. In the **left sidebar**, click **IP**. A submenu opens underneath.
3. In that submenu, click **Firewall**
4. Along the top of the main panel, click the **NAT** tab
5. You'll see the existing rules, including Placeware's two rules and the `3389` one

Before adding anything, check that nothing already uses **`<PUBLIC_IP>`** with port 80 or 443.
Look at the **Dst. Address** and **Dst. Port** columns together. Placeware's rules use
`102.223.1.15` + `80`/`443`. That's fine if your `<PUBLIC_IP>` is different. If you find
`<PUBLIC_IP>` with `80` or `443`, stop and tell me.

- [ ] NAT list open, no existing 80/443 rule for `<PUBLIC_IP>`

### Step 3: Add the HTTPS rule (port 443)

Still on the **NAT** tab, click **Add New**. A blank rule form opens.

> **If a field has no text box next to it**, click the small triangle (▾) beside its name to reveal one.
>
> **Do not tick the little checkbox** next to a field. In MikroTik that means "NOT this value";
> it would invert the rule and break it.

Fill in **exactly** these, leaving everything else untouched:

| Field | What to do |
|---|---|
| **Enabled** | leave ticked ✅ |
| **Chain** | choose `dstnat` from the dropdown |
| **Src. Address** | leave empty |
| **Dst. Address** | type `<PUBLIC_IP>` |
| **Protocol** | choose `6 (tcp)` from the dropdown |
| **Src. Port** | leave empty |
| **Dst. Port** | type `443` |
| **Any. Port** | leave empty |
| **In. Interface** | leave empty |

Now scroll **down** the same form to the **Action** section:

| Field | What to do |
|---|---|
| **Action** | choose `dst-nat` from the dropdown |
| **To Addresses** | Case A: `<SERVER_LAN_IP>` · Cases B/C: the **inner router WAN IP** from Step 1 |
| **To Ports** | Cases A/B: `443` · Case C: `8443` |

Optional but helpful: in **Comment** (top of the form), type `<PREFIX> HTTPS`, so you can tell it
apart from Placeware's rules later.

Click **OK** at the top to save. The new rule appears in the list.

- [ ] Port 443 rule saved

### Step 4: Add the HTTP rule (port 80)

Click **Add New** again. Identical to Step 3, except the ports:

| Field | Value |
|---|---|
| **Chain** | `dstnat` |
| **Dst. Address** | `<PUBLIC_IP>` |
| **Protocol** | `6 (tcp)` |
| **Dst. Port** | **`80`** |
| **Action** | `dst-nat` |
| **To Addresses** | same as Step 3 |
| **To Ports** | Cases A/B: **`80`** · Case C: **`8080`** |
| **Comment** | `<PREFIX> HTTP` |

Click **OK**.

> **Why port 80 matters even though the app is HTTPS:** Let's Encrypt proves you own the domain
> by contacting port 80. Skip this rule and the certificate can never be issued, so the browser
> warning stays permanently. Renewals need it too, so it stays open after go-live.

- [ ] Port 80 rule saved

### Step 5: Add the port forwards on the inner router (Cases B and C)

1. Browser → `http://<INNER_ROUTER_IP>` → log in
2. Top menu → **Advanced**
3. Left sidebar → **NAT Forwarding** → **Port Forwarding**
4. Click **Add** for each row below. Device IP Address = `<SERVER_LAN_IP>`, Protocol `TCP`,
   **Enable This Entry** ticked, then **Save**.

**Case B**

| Service Name | Device IP | External Port | Internal Port | Protocol |
|---|---|---|---|---|
| `<PREFIX>-https` | `<SERVER_LAN_IP>` | `443` | `443` | TCP |
| `<PREFIX>-http` | `<SERVER_LAN_IP>` | `80` | `80` | TCP |

**Case C** (Placeware's two 80/443 rows stay as they are; add these alongside)

| Service Name | Device IP | External Port | Internal Port | Protocol |
|---|---|---|---|---|
| `<PREFIX>-https` | `<SERVER_LAN_IP>` | `8443` | `443` | TCP |
| `<PREFIX>-http` | `<SERVER_LAN_IP>` | `8080` | `80` | TCP |

> **Give the server a fixed address**, or these rules break the day the server's IP changes. On
> the TP-Link: **Advanced** → **Network** → **DHCP Server** → **Address Reservation** → **Add**.
> Pick the server from the device list (or type its MAC address) and set IP `<SERVER_LAN_IP>`.

- [ ] Inner router forwards present and enabled (or Case A: skipped)

---

## Stage 5: Test it from outside

Use a **phone on mobile data**. Office Wi-Fi won't prove anything; it can reach the server
internally and give a false result.

1. Open `http://<DOMAIN>` (plain **http**). It should jump to `https://<DOMAIN>`.
2. You'll see a certificate warning ("Your connection is not private"). Tap **Advanced** →
   **Proceed**. Then you should see the **app's login page**.

**That warning is expected and correct at this stage.** Seeing the app's login page behind it means
the whole chain works for both ports. Stage 6 removes the warning.

### If it doesn't work

| What you see | What it means |
|---|---|
| **The router login page** | The MikroTik rules aren't matching. Recheck Steps 3–4. Usually **Chain** isn't `dstnat`, **Dst. Address** isn't exactly `<PUBLIC_IP>`, a "NOT" checkbox got ticked, or **To Addresses** has the wrong IP. |
| **Times out / won't connect** | Traffic reaches the MikroTik but dies after it. Recheck Step 5 (inner router: ports, server IP, entries enabled). Then Stage 3 (firewall), and `docker compose ps` on the server. |
| **The Placeware app** opens instead | Case C mix-up: the MikroTik rule sends `<PUBLIC_IP>` to 443/80 instead of 8443/8080. Fix **To Ports** in Steps 3–4. |
| `https` works but `http` doesn't | The port-80 rule is missing or wrong (Step 4 / Step 5). Fix it, because the certificate needs it. |
| **The app's login page** ✅ | Working. Move to Stage 6. |

- [ ] App login page loads over mobile data, from both `http://` and `https://`

---

## Stage 6: Get the real certificate (removes the warning)

### Why you see the warning

The app currently uses the **self-signed certificate** that `certs-init` made. It encrypts the
connection fine, but no browser trusts a certificate that vouches for itself, so every browser
shows *"Your connection isn't private"* (`NET::ERR_CERT_AUTHORITY_INVALID`).

The fix is a free certificate from **Let's Encrypt**, which every browser trusts. Before issuing
it, Let's Encrypt proves you control `<DOMAIN>`:

```
Let's Encrypt ──HTTP port 80──> http://<DOMAIN>/.well-known/acme-challenge/<token>
                                     │  (routers forward 80 → <SERVER_LAN_IP>)
                                     ▼
                         nginx serves the token from the certbot_www folder
                                     ▲
                         certbot container wrote the token there
```

### Which machine? The app server only

| Machine | Run it? | Why |
|---|---|---|
| **App server** (`<SERVER_LAN_IP>`, the one `<DOMAIN>` reaches) | **Yes, once** | The certificate must live on the machine that answers `<DOMAIN>`. |
| **Dev laptop** | **No** | You use `https://localhost` there, and no public authority issues certificates for "localhost". The local warning is normal and harmless. The same compose file works there; certbot just finds nothing to renew and stays idle. |

You don't need Ubuntu or WSL. Everything runs inside Docker.

### 6a. Confirm the server has the Stage 2 files

On the server, check these exist (File Explorer, or `dir` in PowerShell):
- `<APP_FOLDER>\<COMPOSE_DIR>\docker-compose.yml` containing a `certbot:` service
- `<APP_FOLDER>\deploy\issue-cert.ps1`

- [ ] Both present

### 6b. Re-check port 80 from the internet

On a **phone using mobile data**, open `http://<DOMAIN>`. It should jump to `https://…` and show
the warning (Stage 5). If it times out, fix that first: the script will fail without port 80.

- [ ] Port 80 works from mobile data

### 6c. Run the certificate script (on the server)

1. On the server, make sure **Docker Desktop** is open and says **Engine running**.
2. Press the **Windows key**, type **PowerShell**, and open **Windows PowerShell** (admin isn't needed).
3. Go to the compose folder:
   ```powershell
   cd "<APP_FOLDER>\<COMPOSE_DIR>"
   ```
4. Run this. It's **one line**; copy all of it:
   ```powershell
   powershell -ExecutionPolicy Bypass -File ..\deploy\issue-cert.ps1 -Email <EMAIL> -Domain <DOMAIN> -WebService <WEB_SERVICE> -CertDir <CERT_DIR>
   ```
   Optional additions at the end of the line:
   - **`-IncludeWww`**: also covers `www.<DOMAIN>`. Only use it if you created the `www` record in Stage 1.
   - **`-InitService ""`**: use this if the project has no `certs-init` service.
   - **`-CertbotService <name>`**: use this if the certbot service has a different name.
   - **`-ComposeDir <folder>`**: lets you run it from a different folder.

The script prints five numbered steps. Each should end with a green **OK**:

| Step | What it does |
|---|---|
| 1 | Starts nginx and certbot, and checks both services exist in the compose file |
| 2 | Writes a test file and fetches it over port 80. This proves nginx serves the check folder. |
| 3 | **Practice run** against Let's Encrypt's test servers. This proves the internet reaches you, without using up real attempts. |
| 4 | Gets the **real** certificate (valid 90 days) |
| 5 | Copies it into `<CERT_DIR>`, reloads nginx (no downtime), and shows the certificate and its expiry |

At the end it lists the certificate and its expiry date (about 90 days away).

- [ ] Script finished with "Done"

### 6d. Check the padlock

1. Close **all** browser windows (browsers remember the old certificate), then reopen.
2. Go to `https://<DOMAIN>`. You should see the **padlock** and no warning.
3. Check on a phone on mobile data too.

- [ ] Padlock shows, no warning (computer and phone)

---

## Renewal: nothing to do

- **Validity:** certificates last **90 days**. The `certbot` container (shows as
  `<PREFIX>-certbot` in Docker Desktop) checks **twice a day** and renews once fewer than 30 days remain.
- **Pickup:** nginx reloads itself every 6 hours to pick up the new certificate.
- **Keep it running:** set **Docker Desktop → Settings → General → Start Docker Desktop when you
  sign in**, and make sure the server signs in after a reboot.
- **Warnings:** Let's Encrypt emails `<EMAIL>` if a certificate is ever close to expiry.

Check the current certificate and its expiry any time (on the server, in `<APP_FOLDER>\<COMPOSE_DIR>`):

```powershell
docker compose run --rm --entrypoint certbot certbot certificates
```

Test that renewal would work, without changing anything:

```powershell
docker compose run --rm --entrypoint certbot certbot renew --dry-run --webroot -w /var/www/certbot
```

---

## If the script stops with FAILED

| Message | What to do |
|---|---|
| **Docker is not running** | Open Docker Desktop, wait for *Engine running*, run again. |
| **docker-compose.yml has no '…' service** | Stage 2.2/2.3 isn't deployed, or the service has another name. Pass `-WebService` / `-CertbotService`. |
| **Step 2: web server did not return the check file** | nginx is missing the `/.well-known/acme-challenge/` block (2.4) or the `certbot_www` mount (2.3). Fix it, then redo 2.6 step 3. |
| **Step 3: could not reach this server on port 80** | Port 80 doesn't get in from the internet. Redo Stage 5 with `http://`, then check Stage 1 (DNS), Stage 4 (both routers, the port-**80** rules) and Stage 3 (firewall). |
| **"too many failed authorizations" / "rate limit"** | Let's Encrypt limits repeated failures. Wait an hour, fix port 80, try again. The practice run exists to avoid this. |
| **Step 5: could not copy the certificate** | The certbot service doesn't mount `ssl_certs` at `<CERT_DIR>` (2.2), or `-CertDir` doesn't match the nginx config (2.4). |
| **Padlock still missing after "Done"** | Close every browser window, or try a private window. Check that the `ssl_certificate` lines in nginx point at `<CERT_DIR>/cert.pem` and `key.pem`. |
| **Port 80/443 "already in use"** when starting the containers | Something else on the server holds the port (IIS, Skype, another web server). Find it in an admin PowerShell with `netstat -ano | findstr ":80 "` (the last number is the process ID; look it up in Task Manager → Details) and stop it. |

---

## Never do these

- **Don't delete the `<PREFIX>_letsencrypt` volume.** It holds the real certificate and account,
  and re-issuing many times hits Let's Encrypt's rate limits.
- **Don't run the script on the dev laptop** for the real domain.
- **Don't close port 80 on the routers after go-live.** Renewal needs it every ~60 days.
- **Don't edit or delete Placeware's NAT rules** while adding the new ones (Case C especially).

---

## Then you're live

`https://<DOMAIN>`: clean address, valid certificate, reachable from anywhere.

---

## Server is Linux instead of Windows?

Stages 0–2, 4 and 5 are identical. For Stage 3, use `sudo ufw allow 80,443/tcp`. Replace Stage 6c
with these commands, run in `<APP_FOLDER>/<COMPOSE_DIR>`:

```bash
docker compose up -d certs-init <WEB_SERVICE> certbot
docker compose run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot \
  -d <DOMAIN> --email <EMAIL> --agree-tos --no-eff-email --non-interactive --dry-run      # practice
docker compose run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot \
  -d <DOMAIN> --email <EMAIL> --agree-tos --no-eff-email --non-interactive --keep-until-expiring
docker compose run --rm --entrypoint sh certbot -c \
  "cp -L /etc/letsencrypt/live/<DOMAIN>/fullchain.pem <CERT_DIR>/cert.pem && cp -L /etc/letsencrypt/live/<DOMAIN>/privkey.pem <CERT_DIR>/key.pem"
docker compose exec <WEB_SERVICE> nginx -s reload
```

---

## For the consultant: security items (same as Placeware)

Neither blocks go-live. Both should be fixed.

**1. The router's admin page is open to the internet.** That's why WebFig appears when you visit
the domain or the new public IP before the rules exist. On an old RouterOS (Placeware's is
v6.42.11, from 2018), that's a real risk. The port-80 rule hides the symptom, but the service is
still listening on every public IP, including a new one.
Fix: **IP → Services** → move `www` off port 80 and `www-ssl` off 443, and set *Available From* to
the local network only. A RouterOS update is also overdue.

**2. Remote Desktop (port 3389) is exposed to the internet.** Internet-facing RDP is among the
most common ways ransomware gets into a network. It belongs behind a VPN, or at minimum
restricted by source IP. That matters more now that two clients' data sits on the network.

---

## Full checklist

- [ ] Stage 0: values filled in; public IP decided (new IP added to the MikroTik if needed)
- [ ] `http://<OUTER_ROUTER_IP>` opens the router (lockout check)
- [ ] Stage 1: `nslookup <DOMAIN>` → `<PUBLIC_IP>`
- [ ] Stage 2: volumes, `certs-init`, `certbot`, nginx mounts + reload, nginx port-80 block, script copied; check returns `404`
- [ ] Stage 3: firewall allows 80 and 443
- [ ] Stage 4: MikroTik 443 + 80 rules; inner router forwards (Case B/C); server IP reserved
- [ ] Stage 5: app login loads from mobile data over `http://` and `https://`
- [ ] Stage 6: `issue-cert.ps1` finished with "Done"; padlock on computer and phone
- [ ] Docker Desktop starts with Windows
