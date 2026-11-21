# VMS: Digital Visitor Management

Replaces the paper visitor register. Visitors check in on their own phone by scanning a QR poster, hosts approve from a phone alert or WhatsApp, and guards verify passes in a phone browser. No hardware, no app installs.

This guide covers installing, starting and using the system. The design (data model, API routes, decisions) is in [docs/PROPOSAL.md](docs/PROPOSAL.md).

> **About the addresses in this guide.** `localhost` means "this computer": an address like `https://localhost:5173` only opens in a browser **on the computer running VMS**, after you start it (section 1). Other devices, such as phones and other PCs, use that computer's own address instead: on your Wi-Fi its local address (find it with `ipconfig`; `192.168.1.12` below is only an example), or on a server the public address you set up (e.g. `https://203.0.113.10:8443`, see [docs/public-setup.md](docs/public-setup.md)). None of these addresses open from GitHub.

- [1. Install and start (Windows)](#1-install-and-start-windows)
- [2. Other ways to run it](#2-other-ways-to-run-it)
- [3. Logging in](#3-logging-in)
- [4. Setting up a new organization](#4-setting-up-a-new-organization)
- [5. Day-to-day use](#5-day-to-day-use)
- [6. WhatsApp, or running without it](#6-whatsapp-or-running-without-it)
- [7. Going to production](#7-going-to-production)
- [8. Maintenance](#8-maintenance)
- [9. Tests](#9-tests)
- [10. Troubleshooting](#10-troubleshooting)
- [11. For developers](#11-for-developers)

---

## 1. Install and start (Windows)

**You need**
- [uv](https://docs.astral.sh/uv/) (it installs the right Python by itself)
- [Node.js](https://nodejs.org/) 20 or later

No database, Redis, Docker or MinIO is needed for local use: the API runs its own embedded PostgreSQL, an in-process stand-in for Redis, and stores photos on disk.

**Start everything:** double-click **`start.bat`** in the project folder (or run it from a terminal). It:

1. creates `api\.env` with local settings, on the first run only, and points QR codes at this computer's Wi-Fi address so phones can use them;
2. starts PostgreSQL and applies any new database changes;
3. loads demo data, on the first run only;
4. starts the API and the web app, each in its own window;
5. waits until both answer, then opens the app in your browser at this computer's Wi-Fi address (e.g. `https://192.168.1.12:5173`). Accept the certificate warning once (see [Using phones on your Wi-Fi](#using-phones-on-your-wi-fi)).

It is safe to run again at any time: whatever is already running is left alone. The first run downloads packages and takes a few minutes; later starts take seconds.

| What | Where |
|---|---|
| The app | `https://localhost:5173` |
| Mock WhatsApp inbox (local only) | `https://localhost:5173/dev/whatsapp` |
| API documentation | `http://localhost:8000/api/docs` |

**Stop:** close the **VMS API** and **VMS web** windows. PostgreSQL keeps running in the background (it uses little); to stop it too:

```powershell
cd api; uv run python scripts/local_pg.py stop
```

## 2. Other ways to run it

### By hand (Windows, macOS, Linux)

```bash
cd api
uv run python scripts/local_pg.py start        # embedded PostgreSQL on port 54329
```

Create `api/.env` (first time only):

```
ENV=dev
DATABASE_URL=postgresql+asyncpg://vms_app:vms_app@127.0.0.1:54329/vms
DATABASE_ADMIN_URL=postgresql+asyncpg://vms:vms@127.0.0.1:54329/vms
REDIS_URL=memory://
STORAGE_BACKEND=local
```

```bash
uv run alembic upgrade head                    # database tables (run again after updates)
uv run python -m scripts.seed                  # demo data (once)
uv run python scripts/dev_api.py               # API on :8000, reloads on code changes
```

In a second terminal:

```bash
cd web
npm install                                    # first time
npm run dev                                    # web on :5173, forwards /api to :8000
```

### With Docker

```bash
docker compose up --build
docker compose exec api python -m scripts.seed
```

This runs PostgreSQL, Redis, MinIO (photo storage, console on `http://localhost:9001`), the API, the background worker and the web app, with the same addresses as above. The Docker setup has not been tested on this machine.

## 3. Logging in

The demo data creates *Kalinga Infotech*, with two sites, ten hosts and a few weeks of visits. The password for every demo account is `demo-password-123`.

| Who | Sign in with | Lands on |
|---|---|---|
| Org admin | `admin@kalinga.demo` | `/admin` |
| Guard | `9861000002` | `/guard` (gate console) |
| Host | no password: as admin, open the host under **People** (e.g. Meera Iyer) and use *Create link*; open that link (in another browser, or on a phone) | `/host` |
| Super admin | `root@vms.local`, at `https://localhost:5173/platform` | `/platform` |

VMS runs **without WhatsApp** by default: there are no visitor codes, hosts approve in the host app (with phone alerts), and links are shared from people's own WhatsApp. [Section 6](#6-whatsapp-or-running-without-it) explains this, and how to try the WhatsApp flows with the mock inbox.

### Using phones on your Wi-Fi

`start.bat` points QR codes and links at this computer's **Wi-Fi address**, e.g. `https://192.168.1.12:5173`, so phones on the same Wi-Fi can scan them. It checks the address on every start, so it follows along if the router hands out a new one.

1. Connect the phone to the **same Wi-Fi** as this computer.
2. Download the QR posters again after the address changes (*Sites & gates*); old posters keep the old address.
3. The first time each phone opens the app, it warns that the connection isn't private, because the certificate is made by this computer. Tap *Advanced → Proceed* (Chrome) or *Show details → visit this website* (Safari). The https address is what lets the guard's camera scanner work: browsers only allow the camera on https.
4. If a phone can't load the page at all, Windows Firewall is blocking it. When Windows asks, allow **Node.js**. Otherwise allow it under *Windows Security → Firewall → Allow an app through firewall*.

Good to know:
- **WhatsApp links:** WhatsApp doesn't make bare addresses like these tappable, so people copy links into the browser.
- **Phone alerts:** alerts for hosts need a real certificate, so they don't work here (see section 7).
- **This computer only:** to keep everything on `localhost` with no phones, put `LAN_ADDRESS=off` in `api\.env`.
- **Reaching it from outside your Wi-Fi:** see [docs/public-setup.md](docs/public-setup.md).
- **Browser tests:** `npm run e2e` expects the mock WhatsApp, and follows the https setting by itself.

## 4. Setting up a new organization

1. Open `https://localhost:5173/signup` and create the organization and its first admin.
2. The **setup wizard** opens and walks through six steps:
   1. **Organization**: logo, colours, the language visitors see first, and a privacy contact.
   2. **First site and gate**, e.g. "Head office", "Main gate".
   3. **Hosts**, the people visitors come to see. Import a CSV (the dialog has a template) or add them one by one. Each needs a mobile number.
   4. **Check-in form**: selfie on or off, ID proof (only the type and last 4 characters are ever stored), purposes of visit. Extra fields (laptop serial, PPE, NDA…) go under **Check-in form** in the admin menu.
   5. **QR posters**: download the A4 PDF for each gate, print it in colour and put it up at reception.
   6. **Test visit**: you get a real approval request (on WhatsApp, or as a phone alert without WhatsApp); approve it to finish.
3. Add your guards under **People** (role *Guard*, with a password) and assign their sites. The dashboard shows a checklist until everything is done.

## 5. Day-to-day use

### Visitors (their own phone)

1. Scan the poster (or open the gate's link), enter their mobile number and the WhatsApp code. Without WhatsApp (or with *Settings → Visitors confirm their number* off) there is no code: the number is just typed in, and the guard sees "Number not verified: check their ID".
2. Fill in name, company, who they're visiting and why; take a selfie; accept the privacy notice.
3. Wait on that page: it updates when the host answers. Once approved, the page (and WhatsApp, if on) shows a **pass** with a QR code.
4. Show the pass to the guard.

Returning visitors who confirmed their number with a code get their details pre-filled. Without a code nothing stored under the number is shown, since anyone could type it. English or Hindi, switchable on every page.

### Hosts (WhatsApp and/or phone alerts, host app)

- A request arrives on WhatsApp with **Approve**, **Ask to wait** and **Reject**, and a link to the visitor's photo and details.
- **Phone alerts (web push):** in the host app, *Turn on alerts* once per phone. Requests then show up as notifications with **Approve** and **Decline**, even when the app is closed. Free, no account with anyone. Works in Chrome, Edge and Firefox on Android and computers; on iPhone (iOS 16.4+) only after *Share → Add to Home Screen* and opening it from there. Without WhatsApp this is how hosts hear about visitors.
- No answer in time (*Settings → Approvals*) and it goes to the host's backup host (set under **People**), and to theirs, up to the number of steps set there. If nobody answers, the visitor is told to check with reception.
- In the host app (`/host`), hosts can see who's waiting, today's visitors and history, and create **invites**: pre-approved passes sent to guests on WhatsApp (without WhatsApp, the host sends them with *Share on WhatsApp* from their own phone), for one visit, a group, or several days within set hours.

### Guards (gate console, any phone)

- **Scan**: point the camera at the pass. A big result says what to do: approved, already inside, expired, wrong site, blocked… with the photo to compare. Then **Check in** or **Check out**. A field below takes a pass link or code typed in, or from a handheld scanner.
- **Visitors**: everyone waiting for a host, approved, expected today (invites), on site (with a head count) and left. *Remind host* sends a WhatsApp nudge.
- **Walk-in**: register someone at the desk, either asking the host or letting them in directly with a reason (recorded and the host is told).
- **Blacklist**: blocked people are refused with "please speak to security"; flagged people come in with an alert.
- **Evacuation**: at the bottom of the Visitors tab, a PDF roll call and *Send to safety contacts* (without WhatsApp: *Share list on WhatsApp*, which opens the guard's own WhatsApp with the message and a live-list link, e.g. for a safety group).
- **When the connection drops**, the console keeps working as long as it stays open:
  - Passes are checked on the phone against today's list, which it refreshes every minute while online.
  - Check-ins and check-outs are saved and sent when the connection returns; the server re-checks each one.
  - A pass approved after the last refresh shows as "genuine, but not on today's list".
  - Reloading or reopening the page needs a connection.
- People still inside at the end of the day (*Settings → Auto check-out*) are checked out automatically.

### Admins (`/admin`)

| Menu | What it's for |
|---|---|
| Dashboard | Who's on site, waiting for hosts, today's check-ins, answer times, live activity |
| Visit log | Every visit, filtered and searchable; click one for its full history; export CSV, Excel or PDF |
| Reports | Daily traffic, busiest hours, top hosts and departments, approval times; PDF report |
| Evacuation | Everyone on site now with phone numbers; printable roll call; WhatsApp to the site's safety contacts |
| Sites & gates | Sites, gates, QR posters, new QR codes (old posters stop working), safety contacts |
| People | Hosts, guards, admins; CSV import; backup hosts; guards' sites; one-time **sign-in links** to share yourself |
| Check-in form | Purposes and extra fields per site |
| Invites / Blacklist | Pre-approved guests; people to block or watch for |
| Privacy | Data retention, a person's data (download or erase), visitors' erasure requests, the privacy notice text |
| Settings | Name, logo, colours, approval timeouts, auto check-out time, selfie and ID rules, retention period, privacy contact |
| Audit log | Every admin action |
| Gate console | The guard screen, for any site |

**Privacy (DPDP Act):**
- **Retention:** visitor data is anonymized after the retention period (*Settings*, default 90 days). Visit counts stay for reports.
- **Visitors' own page:** at `/privacy/<organization>` (linked from the check-in form) a visitor can see and download their data, and ask for it to be erased. It needs a WhatsApp code; without WhatsApp the page points them to the privacy contact, and an admin handles it under **Privacy**.
- **Erasure requests:** these appear under **Privacy**; erasing or declining sends the visitor a WhatsApp message.

### Super admin (`/platform`)

- Lists every organization with its staff and site counts.
- Create, suspend or reactivate an organization. Suspending one blocks its staff and its QR codes.
- Shows the shared WhatsApp number's health: messages sent, failed and skipped in the last 24 hours, and the common errors.

### Languages

Visitor, guard, host, pass and privacy screens are in English and Hindi; the admin and platform screens are English. Adding a language: [docs/adding-a-language.md](docs/adding-a-language.md).

## 6. WhatsApp, or running without it

### Without WhatsApp (no business account needed)

This is the default (`WHATSAPP_PROVIDER=off` in `api/.env`; installs from before this default may still say `mock`, so change it and restart). Then:

| Normally on WhatsApp | Without WhatsApp |
|---|---|
| Visitor's 6-digit code | No code; guards see "Number not verified: check their ID" |
| Host's approval request, reminders, arrivals | Phone alerts (web push) from the host app, with Approve / Decline. Each host turns on alerts once on their phone; until then they only see visitors while the host app is open |
| Visitor's answer and pass | On the visitor's own screen, which updates live; they keep it open or take a screenshot |
| Invite passes to guests | The host taps *Share on WhatsApp* next to each guest: their own WhatsApp opens with the invitation typed in |
| Sign-in links for hosts | The admin opens the person under **People → Create link** and shares it the same way (works once, within 3 days) |
| Evacuation message to safety contacts | *Share list on WhatsApp* opens the guard's own WhatsApp with the message, e.g. for a safety group |
| Visitor's own privacy page | Shows the privacy contact; an admin handles requests under **Privacy** |

For phone alerts in production, set `VAPID_PRIVATE_KEY` (the command is in [.env.example](.env.example)) and `VAPID_SUBJECT`, and serve the site over HTTPS (browsers only allow alerts on HTTPS or localhost). Changing the key means everyone has to turn alerts on again.

Phone alerts need a real certificate, so test them on a server with a domain, not on the local Wi-Fi setup.

### With WhatsApp

**To try it locally,** set `WHATSAPP_PROVIDER=mock` in `api/.env` and restart. Nothing is sent: messages appear in the mock inbox at `/dev/whatsapp`, where tapping a button behaves exactly like a real reply. Type `STOP` or `START` there to try opting out. The browser tests (`npm run e2e`) need this mode.

**To send real messages** through the Meta WhatsApp Business Cloud API (one shared number for all organizations):

1. In [Meta for Developers](https://developers.facebook.com/), create a Business app with the WhatsApp product and add your business phone number. Create a System User token with `whatsapp_business_messaging` and `whatsapp_business_management`.
2. Set in `api/.env`:

   ```
   WHATSAPP_PROVIDER=meta
   WHATSAPP_PHONE_NUMBER_ID=...          # WhatsApp > API setup
   WHATSAPP_ACCESS_TOKEN=...             # the System User token
   WHATSAPP_WABA_ID=...                  # WhatsApp Business Account ID
   WHATSAPP_APP_SECRET=...               # App settings > Basic (verifies webhooks)
   WHATSAPP_VERIFY_TOKEN=...             # any random string, also entered in step 4
   PUBLIC_WEB_URL=https://vms.example.in # message buttons link here; set it before step 3
   ```
3. Submit the message templates (English and Hindi) and wait until Meta approves them, from minutes to a day:

   ```bash
   cd api
   uv run python -m scripts.whatsapp_templates create
   uv run python -m scripts.whatsapp_templates status    # every row should say APPROVED
   ```
4. In the Meta app, under WhatsApp > Configuration, set the webhook URL to `https://<your api host>/api/v1/webhooks/whatsapp` with your verify token, and subscribe to `messages`.
5. Check **Shared WhatsApp number** in the platform console.

**Good to know:**
- **Opting out:** anyone who sends STOP gets no more messages until they send START or ask for a code themselves.
- **24-hour window:** confirmations to hosts ("Done: approved") are sent only within 24 hours of their last message (WhatsApp's rule). Everything else is a pre-approved template and works any time.
- **No photos in chats:** visitor photos are never sent into chats (they would outlive the retention period); hosts open them through a link that expires.

## 7. Going to production

**Running it from this PC on a static IP and its own port?** Follow [docs/public-setup.md](docs/public-setup.md). **A fresh server in another office?** Follow [docs/new-server.md](docs/new-server.md): one script switches the settings (`scripts.go_public`), and `serve-public.bat` runs everything on one HTTPS port. The rest of this section is for a proper server.

Set at least these in the API's environment (all variables are explained in [.env.example](.env.example)):

| Variable | Value |
|---|---|
| `ENV` | `prod` (hides the API docs and the mock inbox) |
| `PUBLIC_WEB_URL`, `CORS_ORIGINS` | your web address |
| `JWT_SECRET` | a long random string (the command is in `.env.example`) |
| `PASS_SIGNING_KEY` | an Ed25519 private key; it signs every visitor pass (the command is in `.env.example`) |
| `COOKIE_SECURE` | `true` (HTTPS only) |
| `DATABASE_URL`, `DATABASE_ADMIN_URL` | PostgreSQL **15 or later**, with two roles: `vms_app` (restricted) and `vms` (owner). `infra/postgres/init.sql` creates them. |
| `REDIS_URL` | a real Redis |
| `STORAGE_BACKEND=s3`, `S3_*` | an S3 bucket in `ap-south-1` (Mumbai), private |
| `WHATSAPP_*` | see section 6 (`WHATSAPP_PROVIDER=off` to run without WhatsApp) |
| `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | key for phone alerts (web push), see section 6 |

Run:
- **Migrations:** `alembic upgrade head`, on every deploy.
- **API:** `uvicorn app.main:app`.
- **Worker:** `arq app.workers.settings.WorkerSettings` (message retries, escalations, expiry, auto check-out, retention, exports).
- **Web:** `npm run build` in `web/`; serve `web/dist` as static files, with `/api` forwarded to the API and every other path falling back to `index.html`.

Keep `PASS_SIGNING_KEY` and `JWT_SECRET` safe and stable: changing the pass key invalidates every issued pass.

## 8. Maintenance

- **Updating:** pull the new code and run `start.bat` again. It applies database changes before starting the API. By hand, run `uv run alembic upgrade head` in `api/`.
- **Background jobs** run every 15 seconds:
  - retry failed messages
  - escalate unanswered visits and expire the ones nobody answered
  - auto check-out at the end of the day
  - close ended invites
  - delete export files after 24 hours
  - apply each organization's retention period, every 6 hours
  
  Locally they run inside the API; in production, in the worker.
- **Backups:** back up the PostgreSQL database and the photo storage together.
- **Local data** lives in `api/.pgdata` (database) and `api/.media` (photos). To start over: stop everything, delete both folders and `api/.env`, and run `start.bat`.
- **Visitor page size:** the check-in page must stay under 120 KB (gzipped) for slow phones; `npm run size` in `web/` checks it.

## 9. Tests

```bash
cd api && uv run pytest      # API: auth, tenant isolation, check-in, approvals, gate, invites,
                             # reports, WhatsApp, privacy, offline passes, onboarding
cd web && npm test           # web unit tests
cd web && npm run e2e        # browser tests: needs the app running with demo data (start.bat)
cd web && npm run size       # visitor page size budget
```

The API tests start their own embedded database. `npm run e2e` uses your installed Chrome; on a CI machine, run `npx playwright install chromium` and set `E2E_CHANNEL=` (empty).

## 10. Troubleshooting

| Problem | What to do |
|---|---|
| `start.bat` says uv or npm is not installed | Install it (section 1), then open a new terminal so it's on the PATH |
| A window closes or shows an error | Read the **VMS API** / **VMS web** window. The database log is `api/.pgdata.log`. |
| "Port already in use" | Something else uses port 8000, 5173 or 54329. Close it, or stop VMS windows left over from an earlier run. |
| Signed out unexpectedly | Sessions last 14 days of inactivity; sign in again |
| No WhatsApp message arrives locally | WhatsApp is off by default. With `WHATSAPP_PROVIDER=mock`, look in `https://localhost:5173/dev/whatsapp`, not on a phone |
| A pass shows "not valid" after setting a new `PASS_SIGNING_KEY` | Expected: passes signed with the old key no longer verify |
| The gate console shows "No connection" | Passes are still checked against today's list; check-ins sync when the connection is back (section 5) |

## 11. For developers

- **Code layout:**
  - `api/`: FastAPI, SQLAlchemy and Alembic. The code is in `app/` (`api/v1` routes, `services`, `models`, `notifications`, `workers`).
  - `web/`: React, TypeScript, Vite and Tailwind. Features live in `src/features/<area>`.
- **Tenant isolation**, three layers; any one alone stops a cross-organization read:
  - every query is scoped to the caller's organization;
  - PostgreSQL row-level security on every tenant table, applied to the restricted `vms_app` role;
  - composite foreign keys, so rows can't link across organizations.
  
  When adding a tenant table, call `enable_tenant_rls()` and `grant_app_role()` from `app/core/rls.py` in its migration; a test fails otherwise. Every route taking an ID is tested from another organization and must return 404.
- **API conventions:**
  - Base path `/api/v1`.
  - Errors are always `{"error": {"code", "message", "details"}}`.
  - Times are stored and returned in UTC and shown in IST.
  - Phone numbers are stored as E.164.
  - Visit status changes go only through `app/services/visit_state.py`.
- **Privacy rules in code:** never store a full ID number (type + last 4 only). Personal data must be covered by `app/services/privacy.py` (retention and erasure).
