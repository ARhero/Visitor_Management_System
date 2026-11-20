# Setting up VMS on a new server, from scratch

**First, check you need one.** One VMS installation can run any number of offices: each office is a **site** (*Admin → Sites & gates*), with its own gates, QR posters, guards, safety contacts and evacuation list. Hosts and visits are kept per site, and admins see all of them. A separate server is only worth it if that office must be fully independent, with its own data and no link to yours.

If it must, here's the whole setup on a fresh Windows PC or server. Allow about an hour. The result is the same as [public-setup.md](public-setup.md): one HTTPS port on that office's static IP, no demo data, and no public sign-up.

---

## 1. The machine

- Windows 10, 11 or Server; 4 GB RAM and 10 GB free disk are plenty.
- It must stay **on** all the time (it is the gate system), and **not sleep** (*Settings → System → Power*).
- Internet access during installation (to download packages).

## 2. Install the two tools

In PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

That installs **uv**, which runs the Python side and fetches the right Python version itself. Then install **Node.js LTS** from https://nodejs.org (the Windows installer, default options).

Close and reopen PowerShell so both are found.

## 3. Copy the code

On **this** PC, copy the project without its data, keys, settings or downloaded packages. For example, to a USB drive `E:`:

```powershell
robocopy C:\Users\ARhero\Projects\VMS E:\VMS /E /XD .venv node_modules .pgdata .media .media-test .certs dist test-results __pycache__ .git /XF .env .env.dev.bak .pass_signing_key.pem .vapid_key.pem *.log
```

On the new server, copy `E:\VMS` to e.g. `C:\VMS`. (Once the code is in a git repository, you can `git clone` it there instead.)

**Never copy `api\.env` or the `.pem` files between servers.** Each server gets its own keys in step 5.

## 4. Network

Same as [public-setup.md](public-setup.md) steps 1–3, on that office's router and server:
1. Reserve the server's local address in the router (DHCP reservation).
2. Forward a free external port, e.g. `8443` TCP, to that local address, port `8443`.
3. Allow the port in Windows Firewall (PowerShell as Administrator):

   ```powershell
   New-NetFirewallRule -DisplayName "VMS 8443" -Direction Inbound -Protocol TCP -LocalPort 8443 -Action Allow -Profile Any
   ```

## 5. Create the settings

```powershell
cd C:\VMS\api
uv run python -m scripts.go_public https://<that-office-static-ip>:8443
```

This creates `api\.env` with production settings and new secret keys. It also turns off public sign-up and makes the HTTPS certificate. The first run takes a minute while uv downloads Python and the packages.

## 6. Start it

Double-click **`C:\VMS\serve-public.bat`**. The first time, it:
1. installs the web packages and builds the app (a few minutes);
2. creates the database (it lives in `api\.pgdata`) and its tables;
3. starts VMS on port 8443.

Leave the window open.

## 7. Create the super admin

In a second PowerShell window:

```powershell
cd C:\VMS\api
uv run python -m scripts.create_superadmin you@company.com "Your Name"
```

Choose a password of at least 10 characters when asked. This account manages the installation; keep it to one or two people.

## 8. Create the organization

1. In a browser go to `https://<static-ip>:8443/platform/login`.
2. Accept the certificate warning once, then sign in as the super admin.
3. Click **New organization** and fill in:
   - the company name;
   - the first admin's name, email and password;
   - status **Active**.

## 9. Set up the office

Sign out, then go to `https://<static-ip>:8443/login` and sign in as that admin. The **setup wizard** walks through:
- logo, colours and privacy contact;
- the site and gates;
- hosts (CSV import);
- the check-in form;
- QR posters;
- a test visit.

Then:
- **People:** add guards with passwords and assign their site. Create sign-in links for hosts and send them from your own WhatsApp.
- **Privacy:** replace the placeholder privacy notice.
- Print the QR posters and put them up.

## 10. Keep it running

- **Start automatically:** in Task Scheduler, create a task *At log on* that runs `C:\VMS\serve-public.bat`. Make the PC sign in automatically after power cuts, or put it on a UPS.
- **Backups:** regularly close the window and copy `api\.pgdata` (the database) and `api\.media` (photos) somewhere safe. There is no automatic backup yet.
- **Updates:** copy the new code over with the same `robocopy` command (it skips data and settings), then run `serve-public.bat` again. It rebuilds and applies database updates.

## If something goes wrong

| Problem | What to check |
|---|---|
| `uv` or `npm` "not recognized" | Reopen PowerShell after installing; reinstall if needed |
| The browser can't reach the address | Test from a phone on mobile data (routers often can't reach their own public IP from inside), then check the port forward and firewall rule |
| "Address already in use" | Something else uses 8443: run step 5 again with another port, change the forward and firewall rule to match |
| Forgot a password | `uv run python -m scripts.set_password <email>` in `C:\VMS\api` |
