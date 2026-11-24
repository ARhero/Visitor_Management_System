# Office server behind your existing IIS (Microsoft) web server

> Ports 80 and 443 of your static IP free for the VMS computer? [office-server-caddy.md](office-server-caddy.md) is simpler: Caddy on the same computer, no IIS changes.

Use this when **port 443 on your office's static IP is already used by IIS**, the Windows Server that runs your existing website. VMS runs on its own office computer. IIS gets one extra site, `vms.yourcompany.com`, with its own free certificate, and forwards those requests to VMS. The existing website and its settings are not changed.

```
phone ──https──▶ vms.yourcompany.com ──▶ office static IP ──▶ IIS (existing server, port 443)
                                                                  │  new site "vms" + its certificate
                                                                  └──http──▶ VMS computer, port 8080
```

Replace these examples with your own:

| Example | Meaning |
|---|---|
| `yourcompany.com` / `vms.yourcompany.com` | your domain / the new VMS address |
| `203.0.113.10` | the office static IP (where IIS already answers) |
| `192.168.1.5` | the **IIS server's** local address |
| `192.168.1.20` | the **VMS computer's** local address |

**Who does what:**
- **You** do the VMS computer.
- **Whoever manages the IIS server** does Part 4. It needs an administrator on that server and about 30 minutes. Send them this page.
- **The domain person** adds one DNS record.

**Router:** nothing changes. Ports 80 and 443 already go to the IIS server.

---

## Part 1. Ask the domain person

> Please add a DNS record for our domain **yourcompany.com**:
> **Type:** A · **Name/Host:** `vms` · **Value:** `203.0.113.10` (the same IP as our website) · **TTL:** default
> Please don't change any existing records.

Check it later with `nslookup vms.yourcompany.com 8.8.8.8`; it must answer with `203.0.113.10`.

## Part 2. Prepare the VMS computer

The VMS computer is the gate system: if it's off, check-ins stop. Use one that stays in the office and on all the time: Windows 10/11 or Server, 4 GB RAM, 20 GB free disk, wired network, ideally on a UPS.

### 2.1 Fixed local address

1. On the computer, run `ipconfig` and note its **IPv4 Address** (e.g. `192.168.1.20`).
2. In the office router's admin page, reserve that address for this computer (*DHCP → Address reservation*, also called *Static lease* or *Bind IP to MAC*).

### 2.2 Never sleep

PowerShell **as Administrator**:

```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```

Also turn off automatic restarts during office hours (*Settings → Windows Update → Advanced options → Active hours*). If the BIOS has *Restore on AC power loss*, set it to **Power On**.

### 2.3 Install the tools

1. **Git:** https://git-scm.com/download/win, default options.
2. **uv:** in PowerShell (normal, not Administrator):

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
3. **Node.js LTS:** https://nodejs.org, Windows installer, default options.

Close and reopen PowerShell, then check: `git --version`, `uv --version`, `node --version`.

## Part 3. Install and start VMS

1. **Get the code:**

   ```powershell
   git clone https://github.com/ARhero/Visitor_Management_System.git C:\VMS
   ```
2. **Create the settings,** telling VMS that IIS (at `192.168.1.5`) is in front:

   ```powershell
   cd C:\VMS\api
   uv run python -m scripts.go_public https://vms.yourcompany.com --behind-proxy 8080 --proxy-ip 192.168.1.5
   ```
3. **Start it:** double-click **`C:\VMS\serve-public.bat`**. The first run takes a few minutes. It ends with *"VMS is starting on port 8080 (HTTP, for the web server at 192.168.1.5)"*. Leave it open.
4. **Create the super admin,** in a new PowerShell window:

   ```powershell
   cd C:\VMS\api
   uv run python -m scripts.create_superadmin you@yourcompany.com "Your Name"
   ```
5. **Let only the IIS server reach port 8080.** PowerShell **as Administrator**:

   ```powershell
   New-NetFirewallRule -DisplayName "VMS from IIS" -Direction Inbound -Protocol TCP -LocalPort 8080 -RemoteAddress 192.168.1.5 -Action Allow -Profile Any
   ```

   Check it: on the **IIS server**, open `http://192.168.1.20:8080` in a browser. The VMS sign-in page should appear.

---

## Part 4. On the IIS server (for its administrator)

Everything below is added alongside the existing site; nothing existing is modified.

### 4.1 Install two IIS add-ons (if not already installed)

- **URL Rewrite 2.1:** https://www.iis.net/downloads/microsoft/url-rewrite
- **Application Request Routing 3.0 (ARR):** https://www.iis.net/downloads/microsoft/application-request-routing

Close and reopen IIS Manager afterwards.

### 4.2 Turn on forwarding (server-wide setting)

IIS Manager → click the **server name** (top of the tree) → **Application Request Routing Cache** → **Server Proxy Settings…** (right side):
- tick **Enable proxy**;
- **Preserve client IP in the following header:** `X-Forwarded-For`;
- **untick** *Include TCP port from client IP*, so VMS sees the visitor's address without a port number;
- **Response buffer threshold (KB):** `0`, so the visitor's waiting screen updates live;
- **Time-out (seconds):** `300`;
- click **Apply**.

This only lets IIS forward when a site has a rule for it, like the one in 4.5. Existing sites behave as before.

### 4.3 Create the `vms` site

1. Create an empty folder: `C:\inetpub\vms`.
2. IIS Manager → **Sites** → **Add Website…**:
   - **Site name:** `vms`;
   - **Physical path:** `C:\inetpub\vms`;
   - **Binding:** type `http`, port `80`, **Host name `vms.yourcompany.com`** (the host name keeps it apart from the existing site);
   - OK.

### 4.4 Get the certificate with win-acme (free, renews itself)

1. Download win-acme from https://www.win-acme.com (the *x64 trimmed* zip) and unzip it to `C:\win-acme`.
2. Run `C:\win-acme\wacs.exe` **as Administrator** and answer:
   - `N`: create a certificate with default settings;
   - pick the site **vms**;
   - accept the host name `vms.yourcompany.com`, then confirm.

   It verifies the domain over port 80, then installs the certificate and adds an **https binding on 443 for `vms.yourcompany.com` only** (with SNI, so the existing site's certificate is untouched). It also schedules automatic renewal.
3. Check under **vms → Bindings**: there should be `https 443 vms.yourcompany.com`.

**Do 4.4 before 4.5:** the forwarding rule below lets the renewal checks through, but the first certificate is simplest to get while the site is still empty.

### 4.5 Forward the site to VMS

Create `C:\inetpub\vms\web.config` with the content below (change `192.168.1.20` to the VMS computer's address):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <!-- win-acme's certificate renewal checks are answered by IIS itself. -->
        <rule name="Certificate checks" stopProcessing="true">
          <match url="^\.well-known/acme-challenge/" />
          <action type="None" />
        </rule>
        <!-- Plain http: send people to https. -->
        <rule name="To https" stopProcessing="true">
          <match url="(.*)" />
          <conditions>
            <add input="{HTTPS}" pattern="off" />
          </conditions>
          <action type="Redirect" url="https://{HTTP_HOST}/{R:1}" redirectType="Permanent" />
        </rule>
        <!-- Everything else goes to VMS. -->
        <rule name="VMS" stopProcessing="true">
          <match url="(.*)" />
          <action type="Rewrite" url="http://192.168.1.20:8080/{R:1}" />
        </rule>
      </rules>
    </rewrite>
    <security>
      <requestFiltering>
        <!-- Visitor photo uploads (VMS limits them itself). -->
        <requestLimits maxAllowedContentLength="15728640" />
      </requestFiltering>
    </security>
  </system.webServer>
</configuration>
```

No restart is needed; IIS picks it up at once.

---

## Part 5. Test

On a phone on **mobile data**, not office Wi-Fi, open **`https://vms.yourcompany.com`**. It should show the padlock, no warning, and the sign-in page.

---

## Part 6. Create your organization and set it up

1. Go to **`https://vms.yourcompany.com/platform/login`** and sign in as the super admin.
2. Click **New organization** and fill in:
   - the company name;
   - the first admin's name, email and password (10+ characters);
   - **Status: Active**.
3. Sign out, then sign in at `https://vms.yourcompany.com/login` as that admin. The **setup wizard** walks through:
   - logo, colours and privacy contact;
   - site and gate(s);
   - hosts (CSV import or one by one);
   - the check-in form;
   - **QR posters** (print in colour and put up at each gate);
   - a test visit.
4. Under **People**:
   - add **guards**, with role Guard, a password, and their site;
   - for each **host**, click them, then **Create link**, then *Share on WhatsApp*. The host opens the link on their phone and taps **Turn on alerts**.
5. Under **Privacy**, replace the placeholder privacy notice. Under **Settings**, check the approval time and *Passes valid until / auto check-out at*.

## Part 7. Make VMS start by itself

IIS already starts by itself. For VMS, close the `serve-public.bat` window, then in PowerShell **as Administrator**, with your Windows user name (it asks for that account's password):

```powershell
schtasks /Create /TN "VMS" /TR "C:\VMS\serve-public.bat" /SC ONSTART /RU "$env:COMPUTERNAME\YourWindowsUser" /RP * /RL HIGHEST
schtasks /Run /TN "VMS"
```

Restart the VMS computer and test from a phone again (give it 2–3 minutes: VMS rebuilds on each start). To stop or start it later: `schtasks /End /TN "VMS"` / `schtasks /Run /TN "VMS"`.

## Part 8. Backups and updates

**Back up at least weekly**; daily is better. Everything lives on the VMS computer:

| What | Where |
|---|---|
| Database (visits, people, settings) | `C:\VMS\api\.pgdata` |
| Photos | `C:\VMS\api\.media` |
| Settings and keys (without them, passes and sign-ins stop working) | `C:\VMS\api\.env` |

Stop VMS first (`schtasks /End /TN "VMS"`), copy these to another disk or cloud storage, then start it again (`schtasks /Run /TN "VMS"`). Keep the copies private: they hold visitors' personal data.

**Updating VMS:**

```powershell
schtasks /End /TN "VMS"
cd C:\VMS
git pull
schtasks /Run /TN "VMS"
```

**Forgot a password:** `cd C:\VMS\api`, then `uv run python -m scripts.set_password someone@yourcompany.com`.

## Troubleshooting

| Problem | What to check |
|---|---|
| win-acme fails to verify | DNS for `vms` must already point at the static IP; the `vms` site needs its `http` binding on 80 with host name `vms.yourcompany.com`; port 80 must reach IIS (it does if the existing site answers on http) |
| The existing website broke | It shouldn't: everything here is on the separate `vms` site, by host name. Check the `vms` bindings all carry the host name `vms.yourcompany.com` and the https one has SNI ticked |
| **502.3 Bad Gateway** | VMS not running on the VMS computer (`serve-public.bat` window or the scheduled task), wrong address in `web.config`, or the firewall rule in Part 3.5 |
| **404** from IIS on every page | URL Rewrite isn't installed, or *Enable proxy* (4.2) isn't ticked |
| The visitor's waiting screen doesn't update by itself | *Response buffer threshold* must be `0` (4.2). The page still refreshes every 10 seconds anyway |
| Sign-in loops back to the login page | The address given to `go_public` must be exactly `https://vms.yourcompany.com` |
