# Running VMS on your static IP (its own port)

This puts VMS on the internet at `https://<your-static-ip>:<port>`, served by this PC through a port forward on your router. Your other services on the same IP keep their own ports.

**What you get:** visitors, guards and hosts can use it from anywhere, on Wi-Fi or mobile data, and the guard's camera scanner works.

**Limits of this option:**
- The certificate is made by this PC, so each phone or computer shows a "not private" warning once.
- Phone alerts for hosts don't work with such a certificate.
- WhatsApp doesn't turn bare IP addresses into tappable links, so people copy links into the browser.

A domain name with a real certificate removes all three limits: see [custom-domain.md](custom-domain.md).

In the steps below, `203.0.113.10` stands for your static IP and `8443` for the port. Use your own.

---

## 1. Give this PC a fixed address on your network

The port forward points at this PC's local address, so that address must not change.

1. Open the router's admin page (often `192.168.1.1`).
2. Find **DHCP → Address reservation** (also called *Static lease* or *Bind IP to MAC*).
3. Reserve this PC's current Wi-Fi address. Run `ipconfig` and use the *Wireless LAN adapter Wi-Fi → IPv4 Address* line, e.g. `192.168.1.12`.

## 2. Forward a port on the router

Pick an external port that nothing else on the static IP uses, e.g. `8443`. Then add a port-forward rule:

| External port | Protocol | Internal IP | Internal port |
|---|---|---|---|
| 8443 | TCP | 192.168.1.12 | 8443 |

Use the same number on both sides; the steps below assume that.

## 3. Let the port through Windows Firewall

Open **PowerShell as Administrator** and run (change the port if needed):

```powershell
New-NetFirewallRule -DisplayName "VMS 8443" -Direction Inbound -Protocol TCP -LocalPort 8443 -Action Allow -Profile Any
```

## 4. Stop the development servers

Close the **VMS API** and **VMS web** windows that `start.bat` opened. Don't run `start.bat` and the public server at the same time.

## 5. Switch the settings to public mode

In a terminal, in the project folder:

```powershell
cd api
uv run python -m scripts.go_public https://203.0.113.10:8443
```

This:
- saves your current settings as `api\.env.dev.bak`;
- sets production mode, the public address and secure cookies, keeping WhatsApp off;
- generates the secret keys production needs;
- makes the HTTPS certificate for your static IP (and this PC's local address).

Keep `api\.env` private: it now holds the keys that sign passes and sessions.

## 6. Lock down the accounts

The demo data uses a password that is printed in the README (`demo-password-123`), so it must not stay usable on the internet.

1. **Super admin:** change its password:

   ```powershell
   uv run python -m scripts.set_password root@vms.local
   ```

2. **Demo organization:** sign in at `/platform` with the new password and **suspend Kalinga Infotech**. That blocks all its demo staff and its QR codes.
3. **Your own staff:** anyone in Starkridge with a weak or shared password gets a new one, either under **People** in the admin panel or with the same script and their email.

Prefer a clean start with no demo data at all? Ask for a fresh database before going live.

## 7. Start it

Double-click **`serve-public.bat`** in the project folder. It:
1. builds the web app;
2. starts the database and applies any database updates;
3. serves everything on port 8443 over HTTPS.

Leave the window open; closing it stops VMS.

## 8. Test from outside

Use a phone on **mobile data**, not your Wi-Fi: many routers can't reach their own public IP from inside the network.

1. Open `https://203.0.113.10:8443`.
2. Accept the warning once: *Advanced → Proceed* in Chrome, *Show details → visit this website* in Safari.
3. Sign in, and try a check-in from a gate QR.

## 9. Before real visitors

In the admin panel:
- **Sites & gates:** download the QR posters again, since they now carry the public address, and put them up.
- **Privacy:** replace the placeholder privacy notice, and set the privacy contact under **Settings**.
- **People → Create link:** give hosts their sign-in links (sent from your own WhatsApp).

## 10. Keep it running

- **Never sleep:** turn off sleep in Windows (*Settings → System → Power*). If the PC sleeps, the gate stops working.
- **Start automatically (optional):** in **Task Scheduler**, create a task *At log on* that runs `serve-public.bat`.
- **Backups:** all data (visits, people, settings) is in the database in `api\.pgdata`, and photos are in `api\.media`. There is no automatic backup yet. Until there is, regularly close the window and copy both folders somewhere safe, such as another disk or cloud storage.

## Updating and going back

- **Updating the code:** close the window and run `serve-public.bat` again. It rebuilds the app and applies database updates.
- **Back to development on this PC:** close the window, copy `api\.env.dev.bak` over `api\.env`, then run `start.bat`.
- **Static IP or port changed:** run step 5 again with the new address, then step 7, and re-download the QR posters.
