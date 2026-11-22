# Office server: complete setup, step by step

This sets up VMS on **a computer in your office**, reachable from anywhere at **`https://vms.yourcompany.com`** with a real certificate. That means:
- no warnings on phones;
- WhatsApp makes the links tappable;
- hosts can get phone alerts.

It runs without WhatsApp, and your existing website is not touched.

> **Is port 443 on your office static IP already used by a Microsoft (IIS) web server?** Then follow [office-server-iis.md](office-server-iis.md) instead: IIS forwards the subdomain to VMS, and Caddy and router changes aren't needed.

Replace these examples everywhere with your own:

| Example | Meaning |
|---|---|
| `yourcompany.com` | your domain |
| `vms.yourcompany.com` | the new address for VMS |
| `203.0.113.10` | your office's static (public) IP |
| `192.168.1.20` | the office computer's local address |

Plan about **2 hours**, plus waiting for the domain person.

---

## Part 1. What you need

- **A computer that stays in the office and on all the time.** It's the gate system: if it's off, check-ins stop. Windows 10/11 or Server, 4 GB RAM, 20 GB free disk, wired network preferred, on a **UPS** if possible.
- **The office internet with the static IP.**
- **Access to the office router's admin page**, for address reservation and port forwarding. If someone else manages it, they'll do steps 3.1 and 7.1.
- **The domain person**, to add one DNS record.
- **An admin account** on the office computer, for the firewall and auto-start steps.

---

## Part 2. Ask the domain person (do this first: it can take up to a day)

Send them:

> Please add a DNS record for our domain **yourcompany.com**:
> **Type:** A · **Name/Host:** `vms` · **Value:** `203.0.113.10` · **TTL:** default (or 1 hour)
> It's for a new system at `vms.yourcompany.com`. Please don't change any existing records.

Carry on with Parts 3–6 meanwhile. You'll check the record in Part 8.

Also confirm with whoever set up your internet (or the provider) that:
- `203.0.113.10` is a **public static IP** that reaches the office router;
- incoming ports **80 and 443** aren't blocked by the provider and aren't already forwarded to something else.

If 443 is already used for something, stop here and ask for a different plan.

---

## Part 3. Prepare the office computer

### 3.1 Give it a fixed local address

1. On the computer, run `ipconfig` and note the **IPv4 Address** of the network it uses (e.g. `192.168.1.20`).
2. In the router's admin page, find **DHCP → Address reservation** (also called *Static lease* or *Bind IP to MAC*), and reserve that address for this computer.

### 3.2 Never sleep

In PowerShell **as Administrator**:

```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```

Also turn off automatic restarts during office hours (*Settings → Windows Update → Advanced options → Active hours*).

If the BIOS has *Restore on AC power loss*, set it to **Power On**, so the computer comes back by itself after a power cut.

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

## Part 5. Get VMS and set it up

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
- new secret keys.

**Keep `api\.env` private and backed up** (Part 12): the keys in it sign every visitor pass.

### 5.3 First start

Double-click **`C:\VMS\serve-public.bat`**. The first time it:
1. installs the web packages and builds the app (a few minutes);
2. creates the database (in `C:\VMS\api\.pgdata`);
3. starts VMS.

It ends with *"VMS is starting on port 8080 (HTTP, for the web server at 127.0.0.1)"*. **Leave this window open.**

Check it on the computer itself: open `http://localhost:8080` in a browser. The sign-in page should appear.

### 5.4 Create the super admin

In a **new** PowerShell window:

```powershell
cd C:\VMS\api
uv run python -m scripts.create_superadmin you@yourcompany.com "Your Name"
```

Type a password (10+ characters) twice. This account manages the whole installation; keep it to one or two people.

---

## Part 6. Install Caddy (the web server that holds the certificate)

1. Download Caddy from **https://caddyserver.com/download**: platform *Windows amd64*, no extra plugins. Rename the file to `caddy.exe` and put it in a new folder **`C:\caddy`**.
2. In `C:\caddy`, create a text file named **`Caddyfile`**, with no extension, containing (with your domain):

   ```
   vms.yourcompany.com {
       reverse_proxy 127.0.0.1:8080
   }
   ```

   In Notepad, choose *Save as type: All files* so it isn't saved as `Caddyfile.txt`.

Don't start it yet: it needs the DNS record and the ports (Parts 7–8).

---

## Part 7. Open the way in

### 7.1 Router: forward ports 80 and 443

In the router's admin page (*Port forwarding*, *Virtual server* or *NAT*), add:

| External port | Protocol | Internal IP | Internal port |
|---|---|---|---|
| 80 | TCP | 192.168.1.20 | 80 |
| 443 | TCP | 192.168.1.20 | 443 |

### 7.2 Windows Firewall

PowerShell **as Administrator**:

```powershell
New-NetFirewallRule -DisplayName "VMS web (Caddy)" -Direction Inbound -Protocol TCP -LocalPort 80,443 -Action Allow -Profile Any
```

VMS's own port 8080 stays closed to the outside on purpose. Only Caddy, on the same computer, talks to it.

---

## Part 8. Check the DNS record, then start Caddy

1. Check the record:

   ```powershell
   nslookup vms.yourcompany.com 8.8.8.8
   ```

   It must answer with `203.0.113.10`. If not, wait or ask the domain person to check.
2. Start Caddy, in PowerShell:

   ```powershell
   cd C:\caddy
   .\caddy.exe run
   ```

   Within a minute it should report the certificate was obtained ("certificate obtained successfully"). Errors here are almost always the DNS record, or ports 80/443 not reaching this computer.

---

## Part 9. Test from outside

On a phone on **mobile data**, not the office Wi-Fi (many routers can't reach their own public address from inside), open **`https://vms.yourcompany.com`**:
- it opens with a **padlock and no warning**;
- the sign-in page appears.

---

## Part 10. Create your organization and set it up

1. Go to **`https://vms.yourcompany.com/platform/login`** and sign in as the super admin.
2. Click **New organization** and fill in:
   - the company name;
   - the first admin's name, email and password (10+ characters);
   - **Status: Active**.
3. Sign out, then sign in at `https://vms.yourcompany.com/login` as that admin. The **setup wizard** opens:
   1. organization: logo, colours, privacy contact;
   2. site and gate(s);
   3. hosts: import the CSV (template in the dialog) or add them one by one;
   4. check-in form: selfie, ID rules, purposes;
   5. **QR posters**: download, print in colour, put up at each gate;
   6. test visit.
4. Under **People**:
   - add **guards**, with role Guard, a password, and their site;
   - for each **host**, click them, then **Create link**, then *Share on WhatsApp*. The host opens the link on their phone and taps **Turn on alerts**.
5. Under **Privacy**, replace the placeholder privacy notice with your own text.
6. Under **Settings**, check the approval time and the pass expiry time (*Passes valid until / auto check-out at*).

---

## Part 11. Make it start by itself

Both VMS and Caddy must come back after a restart or power cut, without anyone signing in.

1. **Stop the test runs:** close the Caddy PowerShell window and the `serve-public.bat` window.
2. **Caddy as a Windows service.** PowerShell **as Administrator**:

   ```powershell
   sc.exe create caddy start= auto binPath= "C:\caddy\caddy.exe run --config C:\caddy\Caddyfile"
   sc.exe start caddy
   ```

   (The spaces after `start=` and `binPath=` are required.)
3. **VMS as a scheduled task** that runs at startup under your Windows account. PowerShell **as Administrator**, with your Windows user name; it asks for that account's password:

   ```powershell
   schtasks /Create /TN "VMS" /TR "C:\VMS\serve-public.bat" /SC ONSTART /RU "$env:COMPUTERNAME\YourWindowsUser" /RP * /RL HIGHEST
   schtasks /Run /TN "VMS"
   ```
4. **Restart the computer and test again from a phone** (Part 9). Give it 2–3 minutes after start-up: VMS rebuilds on each start.

To stop VMS later: `schtasks /End /TN "VMS"`. To start it: `schtasks /Run /TN "VMS"`.

---

## Part 12. Backups and updates

**Back up regularly**, at least weekly; daily is better. Everything lives on this one computer:

| What | Where | Why |
|---|---|---|
| Database (visits, people, settings) | `C:\VMS\api\.pgdata` | everything |
| Photos | `C:\VMS\api\.media` | visitor selfies |
| Settings and keys | `C:\VMS\api\.env` | without it, passes and sign-ins stop working |
| Caddy setup | `C:\caddy\Caddyfile` | |

Stop VMS first (`schtasks /End /TN "VMS"`), copy the folders to another disk or cloud storage, then start it again (`schtasks /Run /TN "VMS"`). Keep the copies private: they hold visitors' personal data.

**Updating VMS** when there are new changes on GitHub:

```powershell
schtasks /End /TN "VMS"
cd C:\VMS
git pull
schtasks /Run /TN "VMS"
```

It rebuilds and applies database updates by itself.

**Forgot a password:**

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
| Caddy can't get a certificate | DNS must show your IP first; ports 80 and 443 must be forwarded to this computer and allowed in the firewall; the provider mustn't block them |
| Phone shows "site can't be reached" | Test on mobile data, not office Wi-Fi; check the router forwards and that Caddy is running (`sc.exe query caddy`) |
| "502 Bad Gateway" | VMS isn't running: `schtasks /Run /TN "VMS"`, or run `serve-public.bat` by hand to see its messages |
| Visitor's waiting screen doesn't update by itself | Reload; if it persists, check nothing else (an antivirus web filter, a second proxy) sits between Caddy and VMS |
| Everything stopped after a power cut | BIOS *Restore on AC power loss*, the VMS task (Part 11.3), the Caddy service |
| Office internet's static IP changed | Ask the domain person to update the `vms` record to the new IP |
