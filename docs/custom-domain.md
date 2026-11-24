# Running VMS on a subdomain of your domain

> Complete step-by-step guides for an office computer: [office-server-caddy.md](office-server-caddy.md) (Caddy on the same computer) and [office-server-iis.md](office-server-iis.md) (behind an existing IIS server).

This gives VMS an address like `https://vms.yourcompany.com`, with a real certificate:
- no "not private" warnings on phones;
- WhatsApp makes the links tappable;
- phone alerts for hosts work.

The existing website on `yourcompany.com` is not changed: a subdomain only needs one extra DNS record.

In the steps, `vms.yourcompany.com` and `203.0.113.10` (your static IP) are examples; use your own.

## How it fits together

```
phone ──https──▶ vms.yourcompany.com ──DNS──▶ your static IP ──▶ web server with the certificate ──http──▶ VMS (port 8080)
```

VMS itself doesn't hold the certificate. A web server in front does (Caddy or IIS below): it gets the certificate for free from Let's Encrypt, renews it automatically, and passes requests on to VMS.

**Pick your case:**
- **A. Ports 80 and 443 on the static IP are free**, or can be forwarded to the VMS computer: use **Caddy** on the VMS computer. This is the simplest. It also applies when the existing site is with a hosting company: only DNS is touched there.
- **B. The static IP's port 443 already serves something through IIS** (Windows web server, e.g. the existing `.aspx` site on your own server): add the subdomain to **IIS** and let it forward to VMS.

If you're not sure which, ask whoever runs the existing site:
- Is port 443 on our static IP already used?
- Is it IIS?

---

## 1. Add the DNS record (both cases)

Wherever the domain's DNS is managed (the registrar such as GoDaddy, Cloudflare, or the hosting company's panel), add:

| Type | Name / Host | Value / Points to | TTL |
|---|---|---|---|
| A | `vms` | `203.0.113.10` (your static IP) | default |

It can take a few minutes to an hour to work. Check with `nslookup vms.yourcompany.com`; it should answer with your static IP.

## 2. Switch VMS to run behind the web server (both cases)

Close any running VMS windows. Then, on the VMS computer, in the `api` folder:

```powershell
# Case A (Caddy on this same computer):
uv run python -m scripts.go_public https://vms.yourcompany.com --behind-proxy 8080

# Case B (IIS on another computer, e.g. 192.168.1.5):
uv run python -m scripts.go_public https://vms.yourcompany.com --behind-proxy 8080 --proxy-ip 192.168.1.5
```

This sets the public address and production settings (keeping WhatsApp off). VMS then listens on plain HTTP, port 8080, for the web server only. It trusts the visitor addresses that web server passes on (for rate limits and logs) only when they come from `--proxy-ip`.

If you came from the static-IP setup ([public-setup.md](public-setup.md)), this replaces it. Remove the old router forward and firewall rule for its port, e.g. 8443.

Then double-click **`serve-public.bat`**. It should say *"VMS is starting on port 8080 (HTTP, for the web server at …)"*.

---

## 3A. Caddy on the VMS computer

1. **Router:** forward external ports **80** and **443** (TCP) to the VMS computer's local address. Port 80 is only used to prove you own the domain when getting the certificate.
2. **Windows Firewall** (PowerShell as Administrator):

   ```powershell
   New-NetFirewallRule -DisplayName "Caddy web" -Direction Inbound -Protocol TCP -LocalPort 80,443 -Action Allow -Profile Any
   ```
3. **Download Caddy:** from https://caddyserver.com/download (Windows amd64). Put `caddy.exe` in `C:\caddy`.
4. **Create `C:\caddy\Caddyfile`** containing:

   ```
   vms.yourcompany.com {
       reverse_proxy 127.0.0.1:8080
   }
   ```
5. **Start it:**

   ```powershell
   cd C:\caddy
   .\caddy.exe run
   ```

   On the first start it gets the certificate (it needs the DNS record from step 1 working, and ports 80/443 reachable). Leave the window open. To start it automatically, add `C:\caddy\caddy.exe run --config C:\caddy\Caddyfile` to Task Scheduler (*At startup*), like `serve-public.bat`.

## 3B. IIS in front (existing IIS server)

The complete steps for the IIS administrator are in [office-server-iis.md](office-server-iis.md), Part 4. In short:
- install URL Rewrite and ARR;
- enable the proxy, with no response buffering and the client IP without its port;
- add a `vms` site bound to `vms.yourcompany.com`;
- get its certificate with win-acme;
- add a `web.config` that lets certificate checks through and forwards everything else to `http://<VMS computer>:8080`.

---

## 4. Check it (both cases)

1. From a phone on **mobile data**, open `https://vms.yourcompany.com`. It should load **without any warning**.
2. Sign in, open a gate QR link, and check that a visitor check-in updates live when the host answers.
3. In the admin panel:
   - **Sites & gates:** download the QR posters again, since they now carry the new address;
   - **People → Create link:** send hosts new sign-in links;
   - hosts open the host app and tap **Turn on alerts**, which works now.

## If something goes wrong

| Problem | What to check |
|---|---|
| `nslookup` doesn't show your IP | The DNS record (name `vms`, type A); wait up to an hour |
| Caddy says it can't get a certificate | DNS must already point at your IP, and ports 80 and 443 must reach this computer (router forward and firewall) |
| "Bad gateway" / 502 | VMS isn't running (`serve-public.bat`), or the address/port in the Caddyfile or `web.config` is wrong, or the firewall blocks 8080 from IIS |
| The visitor's waiting screen doesn't update by itself | IIS: response buffer threshold must be `0` (step 3B.2) |
| Sign-in works but you're signed out on refresh | The address in step 2 must match exactly what's in the browser, including `https://` |
