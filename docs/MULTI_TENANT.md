# Multi-tenant SaaS

Gauntlet can run as **single-tenant** (default, personal app) or **multi-tenant SaaS**
(invite-only Google OAuth, one Google Sheet / memory ledger per user).

## Enable

```env
MULTI_TENANT=true
AUTH_MODE=oauth
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
OAUTH_REDIRECT_URI=https://your-api/api/auth/callback
SECRET_KEY=<long-random-at-least-16-chars>
PLATFORM_ADMIN_EMAILS=you@example.com
CONTROL_DB_PATH=/data/gauntlet_control.db   # optional; defaults under data/
CRON_SECRET=<random>                        # multi-tenant tick fans out per user
# Live Sheets (production multi-tenant):
GOOGLE_APPLICATION_CREDENTIALS=secrets/service-account.json
# Local / tests without Google:
MULTI_TENANT_MEMORY_SHEETS=true
REPO_BACKEND=memory
```

**Production hard rules**

- `SECRET_KEY` must not be the known default or shorter than 16 characters (process refuses to start).
- `MULTI_TENANT=true` requires `AUTH_MODE=oauth` in production.
- Open auth is never permitted for multi-tenant production.
- Global `/setup` wizard is disabled; use `POST /api/tenant/provision` (or admin bind).

## Concepts

| Piece | Role |
|-------|------|
| **Control DB** (SQLite) | Users, invites, `user_id → spreadsheet_id` |
| **Data plane** | Per-user Google Sheet (or `mem-{user_id}` memory repo) |
| **Session** | Cookie carries `user_id`; server re-hydrates role + sheet binding |
| **Tenant context** | Request-scoped; scopes response cache, uploads, import locks |

## Admin

- Platform admins: emails in `PLATFORM_ADMIN_EMAILS` (auto-promoted) or `role=platform_admin`.
- `POST /api/admin/invites` `{ "email": "…" }` — create invite.
- `GET /api/admin/invites`, `DELETE /api/admin/invites/{id}`.
- `GET /api/admin/invites/users` — list users.
- `POST /api/tenant/bind` — **platform admin only** (migrate legacy sheet to a user).

## User lifecycle

1. Admin invites email.  
2. User completes Google OAuth (`/api/auth/login`).  
3. Uninvited Google accounts are redirected with `auth_error=not_invited` (SPA shows “Not invited”).  
4. SPA onboarding **Provision ledger** → `POST /api/tenant/provision`.  
5. Domain APIs use **only** that user’s ledger.

## Migration of an existing single-user sheet

Use this when you currently run **single-tenant** (owner password + env `SPREADSHEET_ID`)
and want your real ledger on a **personal multi-tenant account** while keeping admin for
invites / testing.

### Preconditions

1. Google **OAuth Web** client with redirect  
   `https://<your-host>/api/auth/callback`  
   (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `OAUTH_REDIRECT_URI`).
2. Durable control DB: Railway **volume** + `CONTROL_DB_PATH=/data/gauntlet_control.db`
   (or any path on that volume). Without a volume, redeploys wipe users/bindings.
3. Service account still **Editor** on the existing production spreadsheet.
4. Snapshot: note current `SPREADSHEET_ID` and a couple of dashboard totals for smoke checks.
5. Decide testing path: **Demo password** (isolated memory) — do not bind the production
   sheet to a second “test” principal; one sheet → one user.

### Cutover steps

1. Set production env (names only):

   ```env
   MULTI_TENANT=true
   AUTH_MODE=oauth
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   OAUTH_REDIRECT_URI=https://<your-host>/api/auth/callback
   PLATFORM_ADMIN_EMAILS=you@example.com
   CONTROL_DB_PATH=/data/gauntlet_control.db
   SECRET_KEY=<long random ≥16>
   CORS_ORIGINS=https://<your-host>
   APP_ENV=production
   # Keep SA JSON + (temporarily) SPREADSHEET_ID for migrate-env-sheet
   # Owner password login is disabled under multi-tenant — prefer Google Sign-In
   ```

2. Deploy; confirm process starts (`/health`). Production multi-tenant **requires** oauth.

3. Open the site → **Sign in with Google** as the platform admin email  
   (`PLATFORM_ADMIN_EMAILS` auto-stubs that user — no invite required).

4. **Do not** click **Provision ledger** if you want historical data  
   (that creates a **new empty** sheet).

5. Bind the legacy sheet (pick one):

   | Method | When |
   |--------|------|
   | **Settings → Admin · Legacy sheet → “Bind env SPREADSHEET_ID to me”** | Env still has the production id (recommended cutover). |
   | `POST /api/admin/migrate-env-sheet` | Same as above, API-only. |
   | Settings paste URL / `POST /api/tenant/bind` | Explicit id or bind for another user. |

   ```http
   POST /api/admin/migrate-env-sheet
   Cookie: gf_session=…

   # or
   POST /api/tenant/bind
   { "spreadsheet_id": "<legacy id or Sheets URL>", "user_id": "<optional; default self>" }
   ```

6. Verify:

   - `GET /api/auth/me` → `tenant_ready: true`, `role: platform_admin`
   - Dashboard / holdings match pre-cutover totals
   - Demo password (if enabled) still uses isolated memory, not the production sheet
   - Landing does **not** offer owner password under multi-tenant

7. Optional cleanup: blank `OWNER_*` so nobody confuses paths; leave or clear
   `SPREADSHEET_ID` (ignored for user data after bind; only used by migrate-env and health).

### Testing after cutover (same Google account)

| Path | Ledger |
|------|--------|
| Your Google login | Real personal finances (bound sheet) + admin invites UI |
| Demo password | Isolated memory only — safe for UI/API experiments |
| Local `MULTI_TENANT_MEMORY_SHEETS` | Local multi-tenant without Google Sheets |

You cannot attach a second “admin sandbox” Google sheet to the **same** user while the
production sheet is bound (one `spreadsheet_id` per user).

### Rollback

1. Redeploy with `MULTI_TENANT=false` and prior single-tenant auth vars  
   (`AUTH_MODE=dev`, owner password, `SPREADSHEET_ID`, `ALLOW_OPEN_AUTH=false` as before).
2. Google sheet data is unchanged (bind only rewrites the control DB pointer).
3. Control DB volume can remain; single-tenant ignores it.

## Safety invariants

- No global `SPREADSHEET_ID` fallback for multi-tenant user data.  
- Setup wizard (`/setup`) is **disabled** when `MULTI_TENANT=true`.  
- Unique `spreadsheet_id` per user (SQLite unique index + claim API).  
- Cache keys: `t:{user_id}:…`; jobs scoped per tenant; cron tick fans out.  
- Uploads: `uploads/{user_id}/{sha}.bin`.  
- Isolation tests: `backend/tests/test_tenant_isolation.py`.

## Single-tenant (unchanged)

Leave `MULTI_TENANT` unset/false. Existing `SPREADSHEET_ID` + `AUTH_MODE=dev` path works as before.
