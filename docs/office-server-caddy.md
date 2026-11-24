# Office server with Caddy: complete setup on one computer

This sets up VMS and **Caddy** (a small free web server) on **the same office computer**. Visitors, guards and hosts reach it from anywhere at **`https://vms.yourcompany.com`**, with a real certificate:
- no warnings on phones;
- WhatsApp makes the links tappable;
- hosts can get phone alerts.

It runs without WhatsApp, and your existing website is not touched.

```
phone ──https──▶ vms.yourcompany.com ──DNS──▶ office static IP ──router (80, 443)──▶ office computer
                                                                                     ├─ Caddy: certificate, ports 80 + 443
                                                                                     └─ VMS: port 8080, this computer only
```

Replace these examples everywhere with your own:

| Example | Meaning |
|---|---|
| `yourcompany.com` | your domain |
| `vms.yourcompany.com` | the new address for VMS |
| `203.0.113.10` | your office's static (public) IP |
| `192.168.1.20` | the office computer's local address |

Plan about **2 hours**, plus waiting for the domain person.

---

## Part 1. Before you start: check this setup fits

Caddy needs **ports 80 and 443 of your static IP** sent to this computer. That's where Let's Encrypt checks the domain and where visitors arrive. Only one computer can have each port.

1. **Is your existing website on the same static IP?** Run:

   ```powershell
   nslookup yourcompany.com 8.8.8.8
   ```

   - **A different IP:** the website is hosted elsewhere, so there's no clash. Continue.
   - **Your office static IP:** the existing web server already uses 443 (and usually 80) there. **This guide won't work**; use [office-server-iis.md](office-server-iis.md) instead, where the existing IIS forwards to VMS.
2. **Is anything else using ports 80 or 443 on the office router?** Look at the router's *Port forwarding* list, or ask whoever manages it. Neither 80 nor 443 may already be forwarded somewhere else.
3. **Is the static IP really public?** In the router's status page, the **WAN / Internet IP** must match the address shown by https://ifconfig.me on a computer in the office. If they differ, the provider shares the IP between customers, and incoming connections won't reach you. Ask the provider for a real static public IP.

If all three are fine, continue.

---

## Part 2. Ask the domain person (do this early: it can take up to a day)

Send them:

> Please add a DNS record for our domain **yourcompany.com**:
> **Type:** A · **Name/Host:** `vms` · **Value:** `203.0.113.10` · **TTL:** default (or 1 hour)
> It's for a new system at `vms.yourcompany.com`. Please don't change any existing records.

Carry on with Parts 3–7 meanwhile. You'll check the record in Part 8.

---

## Part 3. Prepare the office computer

VMS is the gate system: if this computer is off, check-ins stop. Use one that stays in the office and on all the time: Windows 10/11 or Server, 4 GB RAM, 20 GB free disk, a wired network, ideally on a UPS.

### 3.1 Fixed local address

1. On the computer, run `ipconfig` and note its **IPv4 Address** (e.g. `192.168.1.20`).
2. In the router's admin page, reserve that address for this computer (*DHCP → Address reservation*, also called *Static lease* or *Bind IP to MAC*).

### 3.2 Never sleep, come back after power cuts

PowerShell **as Administrator**:

```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```

- **Updates:** turn off automatic restarts during office hours (*Settings → Windows Update → Advanced options → Active hours*).
- **BIOS:** if it has *Restore on AC power loss*, set it to **Power On**.

---

## Part 4. Install the tools

1. **Git:** https://git-scm.com/download/win, default options.
2. **uv:** in PowerShell (normal, not Administrator):

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
3. **Node.js LTS:** https://nodejs.org, Windows installer, default options.

**Close and reopen PowerShell**, then check all three are found:

```powershell
git --version
uv --version
node --version
```

---

## Part 5. Install VMS

### 5.1 Download the code

```powershell
git clone https://github.com/ARhero/Visitor_Management_System.git C:\VMS
```

### 5.2 Create the settings

```powershell
cd C:\VMS\api
uv run python -m scripts.go_public https://vms.yourcompany.com --behind-proxy 8080
```

The first run takes a few minutes while uv downloads Python and the packages. It creates `C:\VMS\api\.env` with:
- production mode and the new address;
- WhatsApp off and public sign-up off;
- new secret keys;
- VMS listening on port **8080 for this computer only** (Caddy, on the same computer, is the only thing that talks to it).

**Keep `api\.env` private and backed up** (Part 12): the keys in it sign every visitor pass.

### 5.3 First start

Double-click **`C:\VMS\serve-public.bat`**. The first time it:
1. installs the web packages and builds the app (a few minutes);
2. creates the database (in `C:\VMS\api\.pgdata`);
3. starts VMS.

It ends with *"VMS is starting on port 8080 (HTTP, for the web server at 127.0.0.1)"*. **Leave this window open.**

Check it on this computer: open `http://127.0.0.1:8080` in a browser. The sign-in page should appear.

### 5.4 Create the super admin

In a **new** PowerShell window:

```powershell
cd C:\VMS\api
uv run python -m scripts.create_superadmin you@yourcompany.com "Your Name"
```

Type a password (10+ characters) twice. This account manages the whole installation; keep it to one or two people.

---

## Part 6. Install Caddy

1. Download Caddy from **https://caddyserver.com/download**: platform **Windows amd64**, no extra plugins, then *Download*. Create the folder **`C:\caddy`**, move the downloaded file there, and rename it to **`caddy.exe`**.
2. Create the configuration file. In PowerShell (with your domain):

   ```powershell
   Set-Content -Path C:\caddy\Caddyfile -Encoding ascii -Value "vms.yourcompany.com {", "    reverse_proxy 127.0.0.1:8080", "}"
   ```

   Check what it wrote with `Get-Content C:\caddy\Caddyfile`: three lines. That's the whole configuration: serve `vms.yourcompany.com` with an automatic certificate, and pass everything to VMS.
3. Check it:

   ```powershell
   C:\caddy\caddy.exe validate --config C:\caddy\Caddyfile
   ```

   It should end with *Valid configuration*.

---

## Part 7. Open the way in

### 7.1 Router: forward ports 80 and 443

In the router's admin page (*Port forwarding*, *Virtual server* or *NAT*), add:

| Name | External port | Protocol | Internal IP | Internal port |
|---|---|---|---|---|
| VMS http | 80 | TCP | 192.168.1.20 | 80 |
| VMS https | 443 | TCP | 192.168.1.20 | 443 |

### 7.2 Windows Firewall

PowerShell **as Administrator**:

```powershell
New-NetFirewallRule -DisplayName "VMS web (Caddy)" -Direction Inbound -Protocol TCP -LocalPort 80,443 -Action Allow -Profile Any
```

Don't open 8080: VMS only talks to Caddy on this computer. If Windows asks whether to allow Python on the network, choose **Cancel / Don't allow**.

---

## Part 8. Check the DNS record, then start Caddy

1. Check the record (from Part 2):

   ```powershell
   nslookup vms.yourcompany.com 8.8.8.8
   ```

   It must answer with `203.0.113.10`. If not, wait, or ask the domain person to check.
2. Start Caddy for a first test, in PowerShell:

   ```powershell
   cd C:\caddy
   .\caddy.exe run --config C:\caddy\Caddyfile
   ```

   Within a minute or two it should log that the certificate was obtained (*"certificate obtained successfully"*). Leave this window open for now. Errors here are almost always the DNS record, or ports 80/443 not reaching this computer (Part 7, and Part 1 point 3).

---

## Part 9. Test

### 9.1 From outside

On a phone on **mobile data**, open **`https://vms.yourcompany.com`**:
- it shows the **padlock and no warning**;
- the sign-in page appears.

### 9.2 From inside the office

Now try the same address on a phone on the **office Wi-Fi**. Hosts and guards will mostly use it from there.

- **It opens:** good, continue.
- **It doesn't open (but worked on mobile data):** many routers can't reach their own public address from inside. Fix it in the router, either way works:
  - turn on **NAT loopback** (also called *NAT reflection* or *hairpin NAT*), if the router has it;
  - or add a **local DNS entry** (*DNS → Static hosts* / *Local DNS*): `vms.yourcompany.com` → `192.168.1.20`.

  If the router has neither, ask whoever manages the office network. Without one of these, people on the office Wi-Fi can't reach VMS.

---

## Part 10. Create your organization and set it up

1. Go to **`https://vms.yourcompany.com/platform/login`** and sign in as the super admin.
2. Click **New organization** and fill in:
   - the company name;
   - the first admin's name, email and password (10+ characters);
   - **Status: Active**.
3. Sign out, then sign in at `https://vms.yourcompany.com/login` as that admin. The **setup wizard** walks through:
   - logo, colours and privacy contact;
   - site and gate(s);
   - hosts (CSV import, template in the dialog, or one by one);
   - the check-in form: selfie, ID rules, purposes;
   - **QR posters**: download, print in colour, put up at each gate;
   - a test visit.
4. Under **People**:
   - add **guards**, with role Guard, a password, and their site;
   - for each **host**, click them, then **Create link**, then *Share on WhatsApp*. The host opens the link on their phone and taps **Turn on alerts**.
5. Under **Privacy**, replace the placeholder privacy notice with your own. Under **Settings**, check the approval time and *Passes valid until / auto check-out at*.

---

## Part 11. Make everything start by itself

Both must come back after a restart or power cut, without anyone signing in.

1. **Stop the test runs:** close the Caddy window (Part 8) and the `serve-public.bat` window (Part 5.3).
2. **Caddy as a Windows service.** PowerShell **as Administrator**:

   ```powershell
   sc.exe create caddy start= auto binPath= "C:\caddy\caddy.exe run --config C:\caddy\Caddyfile"
   sc.exe start caddy
   ```

   The spaces after `start=` and `binPath=` are required. The service keeps its own copy of the certificate, so it fetches it once more on its first start.
3. **VMS as a scheduled task** that runs at startup under your Windows account. PowerShell **as Administrator**, with your Windows user name; it asks for that account's password:

   ```powershell
   schtasks /Create /TN "VMS" /TR "C:\VMS\serve-public.bat" /SC ONSTART /RU "$env:COMPUTERNAME\YourWindowsUser" /RP * /RL HIGHEST
   schtasks /Run /TN "VMS"
   ```
4. **Restart the computer**, wait 2–3 minutes (VMS rebuilds on each start), and test again from a phone (Part 9).

Handy commands:

| What | Command |
|---|---|
| Stop / start VMS | `schtasks /End /TN "VMS"` / `schtasks /Run /TN "VMS"` |
| Is Caddy running? | `sc.exe query caddy` |
| Restart Caddy (after editing the Caddyfile) | `sc.exe stop caddy` then `sc.exe start caddy` |

---

## Part 12. Backups, updates and passwords

### Backups

Back up at least weekly; daily is better. Everything lives on this one computer:

| What | Where | Why |
|---|---|---|
| Database (visits, people, settings) | `C:\VMS\api\.pgdata` | everything |
| Photos | `C:\VMS\api\.media` | visitor selfies |
| Settings and keys | `C:\VMS\api\.env` | without it, passes and sign-ins stop working |
| Caddy configuration | `C:\caddy\Caddyfile` | |

Stop VMS first (`schtasks /End /TN "VMS"`), copy these to another disk or to cloud storage, then start it again (`schtasks /Run /TN "VMS"`). Keep the copies private: they hold visitors' personal data.

The certificate needs no backup: Caddy renews it automatically, about every two months.

### Updating VMS

When there are new changes on GitHub:

```powershell
schtasks /End /TN "VMS"
cd C:\VMS
git pull
schtasks /Run /TN "VMS"
```

It rebuilds and applies database updates by itself.

### Forgotten password

```powershell
cd C:\VMS\api
uv run python -m scripts.set_password someone@yourcompany.com
```

---

## Troubleshooting

| Problem | What to check |
|---|---|
| `git`, `uv` or `node` "not recognized" | Reopen PowerShell after installing |
| `nslookup` doesn't show your static IP | The DNS record isn't there yet or is wrong: name `vms`, type A, your static IP |
| Caddy can't get a certificate | DNS must show your IP first. Ports 80 and 443 must be forwarded to this computer (7.1) and allowed in the firewall (7.2). Nothing else may use them (Part 1). The provider mustn't block them |
| Works on mobile data, not on the office Wi-Fi | NAT loopback or a local DNS entry in the router (9.2) |
| "Site can't be reached" from outside | Router forwards, firewall rule, and Caddy running (`sc.exe query caddy`) |
| "502 Bad Gateway" | VMS isn't running: `schtasks /Run /TN "VMS"`, or run `serve-public.bat` by hand to see its messages |
| Sign-in loops back to the login page | The address given to `go_public` must be exactly `https://vms.yourcompany.com` |
| Everything stopped after a power cut | BIOS *Restore on AC power loss* (3.2), the VMS task and the Caddy service (Part 11) |
| The office static IP changed | Ask the domain person to update the `vms` record to the new IP |
