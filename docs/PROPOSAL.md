# VMS: Proposed Architecture (Step 1)

Status: **draft, waiting for your approval**. Nothing has been built yet.

---

## 0. Key technical decisions

| Area | Decision | Why |
|---|---|---|
| Repo layout | Monorepo: `api/` (FastAPI) + `web/` (one Vite app) | One `docker compose up`; shared CI |
| Frontend apps | One React app, four route trees (`/v/*` visitor, `/guard/*`, `/host/*`, `/admin/*`), lazy-loaded per tree | Visitor and guard chunks stay small (target < 120 KB gz) and never load admin/chart code |
| Job queue | **ARQ** (async, Redis-backed) | Same async stack as FastAPI, much smaller than Celery; supports delayed jobs (escalation) and cron (auto checkout, retention) |
| Realtime | **SSE** over Redis pub/sub, consumed with `fetch`-based SSE so auth headers work | Every live feature is server→client only; SSE gets through proxies and reconnects on flaky 3G more reliably than WebSockets |
| Multi-tenancy | Shared schema, `org_id` on every tenant table, **plus Postgres Row-Level Security** as a second line of defence | App-level scoping alone fails silently when someone forgets a filter; RLS fails closed |
| Cross-tenant FKs | Composite FKs `(org_id, id)` on tenant tables | The DB itself rejects a visit in org A that points at a host in org B |
| IDs | UUIDv7 primary keys | Not guessable, but still sorted by time for index locality |
| Time | All `timestamptz` stored in UTC; API returns ISO-8601 UTC; UI formats in `Asia/Kolkata` (site timezone field kept for future) | As specified |
| Auth (staff) | Access JWT (15 min, kept in memory) + rotating refresh token (httpOnly cookie, hashed in the DB, reuse detection by token family) | Standard and revocable |
| Auth (visitor) | Phone OTP → short-lived **visitor session JWT** (30 min, scoped to org + phone + gate) | No account |
| Auth (host) | **Magic link sent over WhatsApp** (no password) for the light web view; admins can also set passwords | Hosts never have to "sign up" |
| Pass QR | Compact signed JWT (EdDSA), `exp` = end of the pass window, `jti` checked server-side for revocation and single use | The QR carries no raw IDs and can't be forged; the DB check covers revocation |
| Gate QR | URL `https://<app>/v/<gate_token>`, a random 16-char token that can be rotated | A poster is a public entry point and doesn't need a signature; rotating it invalidates leaked posters |
| Photos | Client compresses to ~640px WebP → multipart upload to API → EXIF stripped, re-encoded → private bucket. Read through 5-minute signed URLs | Fast on 3G; no raw camera metadata is kept |
| PDF | WeasyPrint (HTML → PDF) for posters, evacuation lists and reports | One templating system (Jinja) for every PDF |
| Excel/CSV | `openpyxl` / stdlib `csv`; large exports run as ARQ jobs | Exports don't block requests |
| i18n | `i18next` on the web (namespaced JSON per locale); server-side strings (WhatsApp, PDFs) in `api/app/i18n/<locale>.yaml` | Adding Odia/Tamil means adding files, with no code changes |

---

## 1. Folder structure

```
VMS/
├── docker-compose.yml            # api, worker, web, postgres, redis, minio, minio-init
├── .env.example
├── README.md
├── docs/
│   ├── PROPOSAL.md               # this file
│   └── adr/                      # short decision records as we go
├── api/
│   ├── Dockerfile
│   ├── pyproject.toml            # uv-managed; ruff + mypy + pytest config
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── app/
│   │   ├── main.py               # app factory, routers, middleware
│   │   ├── core/
│   │   │   ├── config.py         # pydantic-settings; all env vars
│   │   │   ├── db.py             # async engine, session, RLS `SET LOCAL app.org_id`
│   │   │   ├── tenancy.py        # TenantContext dependency, scoped query helpers
│   │   │   ├── security.py       # password hashing, JWT, refresh rotation
│   │   │   ├── rbac.py           # require_roles(...) dependencies
│   │   │   ├── rate_limit.py     # Redis sliding-window limiter
│   │   │   ├── idempotency.py    # Idempotency-Key middleware (guard retry queue)
│   │   │   ├── timeutil.py       # UTC/IST helpers
│   │   │   └── errors.py         # problem+json error format
│   │   ├── models/               # SQLAlchemy 2.0 models, one module per aggregate
│   │   ├── schemas/              # Pydantic v2 request/response models
│   │   ├── api/v1/
│   │   │   ├── auth.py  platform.py  org.py  sites.py  departments.py
│   │   │   ├── users.py  purposes.py  custom_fields.py  blacklist.py
│   │   │   ├── public.py         # visitor check-in (gate token / visitor JWT)
│   │   │   ├── host.py  invites.py  guard.py
│   │   │   ├── dashboard.py  visits.py  reports.py  exports.py
│   │   │   ├── privacy.py  audit.py  onboarding.py  streams.py
│   │   │   ├── webhooks.py       # Meta WhatsApp webhook
│   │   │   └── dev.py            # mock WhatsApp inbox (only when ENV=dev)
│   │   ├── services/
│   │   │   ├── visit_state.py    # the ONE place status transitions happen
│   │   │   ├── visits.py  invites.py  passes.py  otp.py
│   │   │   ├── hosts_import.py   # CSV parse, validate, dry-run preview
│   │   │   ├── storage.py        # S3/MinIO, signed URLs, image sanitising
│   │   │   ├── realtime.py       # Redis pub/sub publish helpers
│   │   │   ├── posters.py  exports.py  reports.py
│   │   │   ├── audit.py  retention.py  privacy.py  blacklist.py
│   │   ├── notifications/
│   │   │   ├── base.py           # NotificationProvider protocol
│   │   │   ├── mock_whatsapp.py  # logs to DB, dev UI simulates button taps
│   │   │   ├── meta_cloud.py     # Meta Cloud API + signature verification
│   │   │   ├── sms_mock.py       # SMS fallback interface
│   │   │   ├── templates.yaml    # template names, languages, params, buttons
│   │   │   └── dispatcher.py     # opt-in + 24h window rules, channel fallback
│   │   ├── workers/
│   │   │   ├── settings.py       # ARQ WorkerSettings + cron jobs
│   │   │   └── tasks.py          # send_notification, escalate_visit, auto_checkout,
│   │   │                         # expire_stale, retention_purge, run_export
│   │   ├── templates/            # Jinja: poster.html, evacuation.html, report.html
│   │   └── i18n/                 # en.yaml, hi.yaml (server-side strings)
│   ├── scripts/seed.py           # demo org: 2 sites, 10 hosts, ~300 visits over 30 days
│   └── tests/
│       ├── conftest.py           # real Postgres + Redis (compose services), per-test txn
│       ├── factories.py
│       ├── unit/                 # state machine, pass signing, OTP, CSV parsing
│       ├── integration/          # API flows end to end with the mock provider
│       └── tenancy/              # cross-tenant access matrix over every route
└── web/
    ├── Dockerfile
    ├── package.json  vite.config.ts  tailwind.config.ts  tsconfig.json
    ├── public/                   # PWA manifest, icons
    ├── src/
    │   ├── main.tsx
    │   ├── app/                  # router, providers, error boundary
    │   ├── features/
    │   │   ├── visitor/          # check-in wizard, camera, status, pass
    │   │   ├── guard/            # scanner, queue, manual check-in, checkout
    │   │   ├── host/             # my visitors, invites
    │   │   ├── admin/            # dashboard, log, reports, settings, management
    │   │   ├── onboarding/       # signup wizard, checklist
    │   │   └── auth/
    │   ├── components/ui/        # design-system primitives
    │   ├── lib/
    │   │   ├── api/              # typed client (generated from OpenAPI)
    │   │   ├── sse.ts            # reconnecting stream hook
    │   │   ├── offlineQueue.ts   # IndexedDB retry queue for guard actions
    │   │   ├── camera.ts  image.ts  phone.ts  time.ts
    │   │   └── i18n.ts
    │   └── locales/{en,hi}/*.json
    ├── tests/                    # Vitest unit/component tests
    └── e2e/                      # Playwright: check-in→approve→pass→scan→checkout
```

---

## 2. Database schema

Conventions: every table has `id uuid pk`, `created_at`, `updated_at` (timestamptz, UTC). "**T**" marks tenant tables: they have `org_id uuid not null`, an RLS policy `org_id = current_setting('app.org_id')::uuid`, a unique `(org_id, id)` and composite FKs to other tenant tables. Phones are stored in E.164 (`+919876543210`).

### Enums
- `user_role`: `org_admin`, `guard`, `host` (`super_admin` lives on platform users)
- `visit_status`: `pending`, `waiting`, `approved`, `rejected`, `checked_in`, `checked_out`, `expired`, `cancelled`
- `visit_source`: `qr_self`, `guard_manual`, `invite`
- `invite_kind`: `single`, `multi_day`, `group`
- `notification_channel`: `whatsapp`, `sms`
- `notification_status`: `queued`, `sent`, `delivered`, `read`, `failed`
- `custom_field_type`: `text`, `number`, `select`, `checkbox`, `declaration`
- `id_type`: `aadhaar`, `pan`, `driving_licence`, `voter_id`, `passport`, `company_id`, `other`

### Visit state machine (enforced only in `services/visit_state.py`)

```
                 ┌──────── waiting ────────┐
                 │   (host: "ask to wait")  │
                 ▼                          ▼
 [submit] → pending ──approve──► approved ──scan/check-in──► checked_in ──checkout/auto──► checked_out
              │ │                  │
              │ └──reject──► rejected
              │                    └──(window ends, never arrived)──► expired
              ├──(timeout after all escalations)──► expired
              └──(visitor cancels)──► cancelled
 invite pass scanned → visit created directly as approved → checked_in
```
Every transition is a conditional `UPDATE … WHERE id=:id AND status IN (:allowed)`, so concurrent webhook retries or double taps can't apply twice. Each transition also writes a `visit_events` row.

### Platform tables (no RLS)

**organizations**: `name`, `slug` (unique), `status` (active/suspended/trial), `data_region` (default `ap-south-1`), `default_locale` (`en`), `timezone` (`Asia/Kolkata`), `branding jsonb` {logo_key, primary_color, accent_color}, `settings jsonb` {approval_timeout_min=5, max_escalations=2, auto_checkout_time="20:00", retention_days=90, require_selfie=true, id_proof_mode=off|optional|required, store_id_image=false, otp_channel}, `onboarding jsonb` {steps completed}, `deleted_at`.

**platform_users**: super admins only: `email` unique, `password_hash`, `full_name`, `is_active`, `last_login_at`.

**refresh_tokens**: `subject_type` (user/platform_user), `subject_id`, `token_hash` unique, `family_id`, `expires_at`, `revoked_at`, `replaced_by`, `user_agent`, `ip`.

**webhook_events**: `provider`, `external_id` (unique with provider), `received_at`, `processed_at`, `status`, `payload jsonb`. Inbound idempotency: a duplicate `external_id` is acknowledged with 200 and skipped. The org is resolved from the payload and passed into processing.

### Tenant tables (T)

**sites** (T): `name`, `address`, `city`, `state`, `pincode`, `lat`, `lng`, `map_url`, `directions_text`, `timezone`, `settings_override jsonb`, `is_active`.

**gates** (T): `site_id`, `name`, `qr_token` (unique, rotatable), `qr_rotated_at`, `is_active`.

**departments** (T): `name`, `site_id` (nullable = org-wide). Unique `(org_id, lower(name))`.

**users** (T): `full_name`, `email` (nullable), `phone` (nullable), `password_hash` (nullable), `roles user_role[]` (one person can be admin + host), `department_id`, `designation`, `primary_site_id`, `backup_host_id → users`, `is_active`, `last_login_at`, `employee_code`. Unique `(org_id, lower(email))` and `(org_id, phone)`. Hosts must have a phone.

**guard_site_assignments** (T): `user_id`, `site_id`. Guards only see their sites.

**purposes** (T): `label`, `label_i18n jsonb`, `requires_id_proof` bool, `sort_order`, `is_active`.

**custom_fields** (T): `site_id` (nullable = all sites), `key` (slug), `label_i18n jsonb`, `help_i18n jsonb`, `type`, `options jsonb`, `required`, `applies_to` (`checkin`/`invite`/`both`), `sort_order`, `is_active`. A `declaration` field stores the accepted text version on the visit.

**consent_notices** (T): `version` int, `locale`, `body_markdown`, `purposes jsonb`, `published_at`, `is_current`. Versioned so we can prove what text a visitor agreed to.

**visitors** (T): `phone` (unique per org), `full_name`, `company`, `email`, `last_photo_key`, `preferred_locale`, `first_seen_at`, `last_visit_at`, `visit_count`, `anonymized_at`. Visitors are per-org: no recognition across tenants.

**visits** (T): `site_id`, `gate_id`, `host_id → users`, `visitor_id`, `invite_guest_id` (nullable), `source`, `status`, `purpose_id`, `purpose_note`, `accompanying_count` (0–20), `vehicle_number`, `custom_values jsonb` {key: value}, `photo_key`, `id_type`, `id_last4` (char 4, never full number), `id_image_key` (only if org enables it), `current_approver_id` (changes on escalation), `escalation_level`, `next_escalation_at`, `requested_at`, `responded_at`, `responded_by`, `response_channel`, `host_message` (wait / reject note), `approved_at`, `checked_in_at`, `checked_in_by`, `checked_out_at`, `checked_out_by`, `checkout_method` (guard/auto/self), `pass_jti` (unique), `pass_expires_at`, `blacklist_hit_id`, `anonymized_at`.
Indexes: `(org_id, site_id, status)`, `(org_id, requested_at desc)`, `(org_id, host_id, requested_at desc)`, partial index on `status='checked_in'` for the evacuation list.

**visit_events** (T): `visit_id`, `from_status`, `to_status`, `actor_type` (visitor/host/guard/admin/system), `actor_id`, `channel` (web/whatsapp/system), `meta jsonb`. Used for approval-time metrics.

**invites** (T): `site_id`, `host_id`, `kind`, `title`, `valid_from`, `valid_until`, `daily_start_time`/`daily_end_time` (multi-day), `notes`, `status` (active/revoked/expired), `created_via` (web/whatsapp/csv).

**invite_guests** (T): `invite_id`, `visitor_id` (nullable until first use), `name`, `phone`, `company`, `pass_jti` (unique), `max_uses` (1 for single, null for multi-day), `use_count`, `last_used_at`, `status` (active/revoked/used), `sent_at`.

**consent_records** (T): `visitor_id`, `visit_id`, `notice_id` (→ consent_notices), `locale`, `consented_at`, `ip`, `user_agent`, `withdrawn_at`.

**whatsapp_contacts** (T): `phone`, `opted_in_at`, `opt_in_source`, `opted_out_at`, `last_inbound_at` (for the 24h session window). Covers hosts and visitors.

**notification_logs** (T): `visit_id`/`invite_guest_id` (nullable), `recipient_phone`, `recipient_user_id`, `channel`, `direction` (out/in), `template_key`, `provider`, `provider_message_id` (unique), `status`, `error`, `payload jsonb`, `attempts`.

**blacklist_entries** (T): `phone`, `name`, `reason`, `action` (`block` / `alert`), `site_id` (nullable), `added_by`, `expires_at`, `is_active`.

**audit_logs** (T, append-only: the app DB role has INSERT/SELECT only): `actor_user_id`, `actor_type`, `action` (e.g. `user.import`, `settings.update`), `entity_type`, `entity_id`, `diff jsonb`, `ip`, `user_agent`.

**privacy_requests** (T): `visitor_phone`, `visitor_id`, `kind` (export/erase), `status`, `verified_via` (otp/admin), `requested_at`, `completed_at`, `export_key`, `handled_by`.

**export_jobs** (T): `requested_by`, `kind` (visits_csv/xlsx/pdf, report_pdf), `filters jsonb`, `status`, `file_key`, `expires_at`.

**org_whatsapp_config** (T, optional, Phase 5): `phone_number_id`, `waba_id`, `access_token_encrypted`, `app_secret_encrypted`, `template_overrides jsonb`. Empty = use the platform's shared number.

### Redis only (not in Postgres)
- `otp:{org}:{phone}`: hashed code, attempts, TTL 5 min
- `rl:*`: rate-limit buckets (per phone, IP and gate)
- `idem:{key}`: idempotency results, 24 h
- pub/sub channels `rt:org:{org}`, `rt:site:{site}`, `rt:visit:{visit}`

### Retention / DPDP (Phase 5 job, schema supports it from day 1)
Nightly job per org: visits older than `retention_days` → photos and ID images deleted from storage, PII columns nulled, `anonymized_at` set. Aggregate counts are kept for reports. Visitors with no remaining visits are anonymized the same way. Every purge run is audit-logged.

---

## 3. API routes (`/api/v1`)

Roles: **SA** super admin · **A** org admin · **G** guard · **H** host · **V** visitor session · **P** public (gate token / signed link).

### Auth
| Method | Path | Who | Notes |
|---|---|---|---|
| POST | `/auth/login` | – | email + password → access token + refresh cookie |
| POST | `/auth/refresh` | cookie | rotates the refresh token, detects reuse |
| POST | `/auth/logout` | any | revokes the token family |
| GET | `/auth/me` | any | user, roles, org, sites |
| POST | `/auth/password/forgot` · `/auth/password/reset` | – | |
| POST | `/auth/magic-link` | – | host phone → link over WhatsApp (rate limited) |
| POST | `/auth/magic-link/consume` | – | |
| POST | `/auth/signup` | – | self-serve: creates org + first admin (Phase 1 basic, Phase 5 wizard) |

### Platform (SA)
`GET/POST /platform/orgs` · `GET/PATCH /platform/orgs/{id}` · `POST /platform/orgs/{id}/suspend` · `/reactivate` · `GET /platform/stats`

### Organization & management (A unless noted)
| Method | Path | Notes |
|---|---|---|
| GET/PATCH | `/org` | name, settings |
| PUT | `/org/branding` · POST `/org/branding/logo` | |
| GET/PATCH | `/org/whatsapp` · POST `/org/whatsapp/test` | template mapping, test send |
| CRUD | `/sites` · `/sites/{id}` | |
| CRUD | `/sites/{id}/gates` · `/gates/{id}` | |
| POST | `/gates/{id}/rotate-qr` | invalidates the old poster |
| GET | `/gates/{id}/poster.pdf` · `/sites/{id}/posters.pdf` | branded A4 |
| CRUD | `/departments` | |
| CRUD | `/users` (filter by role/site/dept) | A; H can GET a limited directory |
| POST | `/users/import?dry_run=true` | CSV → preview with per-row errors |
| POST | `/users/import` | commit; audit logged |
| GET | `/users/import/template.csv` | |
| PUT | `/users/{id}/sites` | guard site assignment |
| CRUD | `/purposes` · PUT `/purposes/order` | |
| CRUD | `/custom-fields` · PUT `/custom-fields/order` | |
| GET/POST | `/consent-notices` | new version = new row |
| CRUD | `/blacklist` | A; G can view hits |
| GET | `/audit-logs` | filterable |

### Public visitor check-in (P / V)
| Method | Path | Notes |
|---|---|---|
| GET | `/public/gates/{gate_token}` | branding, site, purposes, custom fields, consent notice, locales |
| POST | `/public/otp/send` | {gate_token, phone}; rate limited per phone/IP/gate |
| POST | `/public/otp/verify` | → visitor JWT + prefill for returning visitors |
| GET | `/public/hosts?q=` | V; typeahead returning name, department and site only (no phones) |
| POST | `/public/uploads` | V; multipart selfie/ID → upload id |
| POST | `/public/visits` | V; create visit + consent record → notify host |
| GET | `/public/visits/{id}` | V; status |
| GET | `/public/visits/{id}/stream` | V; SSE status updates |
| POST | `/public/visits/{id}/cancel` | V |
| GET | `/public/passes/{pass_token}` | P; pass page data (QR, window, directions) |
| POST | `/public/privacy/requests` | OTP-verified export/erase request |

### Host (H)
| Method | Path | Notes |
|---|---|---|
| GET | `/host/visits` | my pending and today's visits |
| POST | `/host/visits/{id}/respond` | {action: approve/reject/wait, message?}. Same service as the WhatsApp buttons |
| CRUD | `/invites` · `/invites/{id}` | H for own invites, A for all |
| POST | `/invites/{id}/revoke` | |
| POST | `/invites/{id}/guests` · `/invites/{id}/guests/import` | group / CSV |
| POST | `/invites/{id}/guests/{gid}/resend` · `/revoke` | |

### Guard (G, site-scoped)
| Method | Path | Notes |
|---|---|---|
| GET | `/guard/queue?site_id=` | pending / approved / on-site |
| GET | `/guard/stream?site_id=` | SSE |
| POST | `/guard/scan` | {qr_payload} → verified pass + visitor card, or a reason it failed |
| POST | `/guard/visits` | manual check-in on behalf of the visitor (OTP optional, set per org) |
| POST | `/guard/visits/{id}/check-in` | Idempotency-Key required |
| POST | `/guard/visits/{id}/check-out` | Idempotency-Key required |
| POST | `/guard/visits/{id}/notify-host` | re-ping the host |

### Dashboard, log, reports (A; H sees own)
| Method | Path | Notes |
|---|---|---|
| GET | `/dashboard/live?site_id=` | on site, pending, average wait, check-ins per gate today |
| GET | `/dashboard/stream` | SSE |
| GET | `/visits` | filters: date range, site, gate, host, dept, purpose, status, q; cursor pagination |
| GET | `/visits/{id}` | includes timeline (visit_events) + signed photo URLs |
| GET | `/evacuation?site_id=` · `/evacuation.pdf` | everyone currently checked in |
| POST | `/evacuation/share` | sends the list to configured safety contacts on WhatsApp |
| GET | `/reports/traffic` · `/reports/peak-hours` · `/reports/top-hosts` · `/reports/departments` · `/reports/approval-times` | `from`, `to`, `site_id`, IST bucketing |
| POST | `/exports` · GET `/exports/{id}` | async CSV/XLSX/PDF → signed download URL |
| GET | `/visitors/{id}` · POST `/visitors/{id}/export` · POST `/visitors/{id}/erase` | DPDP handling by admin |
| GET/PATCH | `/privacy/requests` | |

### Onboarding (A)
`GET /onboarding/checklist` (computed from data + flags) · `POST /onboarding/steps/{step}/complete` · `POST /onboarding/test-visit` (creates a visit to the admin as host via the provider)

### Webhooks & dev
| Method | Path | Notes |
|---|---|---|
| GET | `/webhooks/whatsapp` | Meta verify challenge |
| POST | `/webhooks/whatsapp` | verifies `X-Hub-Signature-256` → stores the webhook_event → enqueues processing → 200 fast |
| GET | `/dev/whatsapp/messages` | ENV=dev only: mock outbox |
| POST | `/dev/whatsapp/messages/{id}/reply` | simulate button tap; goes through the **same** webhook processing code |
| GET | `/healthz` · `/readyz` | |

Web routes: `/v/:gateToken` (check-in), `/p/:passToken` (pass), `/guard`, `/host`, `/admin/*`, `/signup`, `/dev/whatsapp` (mock inbox UI).

---

## 4. Tests that will exist from Phase 1
- **Tenancy matrix**: two orgs are seeded; for every authenticated route, org B's token with org A's resource IDs must return 404 (never 403, which would leak that the ID exists). A second test runs raw SQL as the app role without `app.org_id` set and asserts zero rows (RLS fails closed).
- **State machine**: every allowed and forbidden transition; concurrent approve + reject yields exactly one winner.
- **Pass signing**: tampered, expired, wrong-org, revoked and reused single-use tokens are all rejected.
- **Webhook**: bad signature → 401; the same event delivered twice → one state change, one notification.
- **OTP**: expiry, attempt limit, rate limit.
