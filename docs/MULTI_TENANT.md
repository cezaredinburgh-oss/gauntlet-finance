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

1. Enable multi-tenant + control DB.  
2. Set your email in `PLATFORM_ADMIN_EMAILS`.  
3. Log in with OAuth.  
4. Platform admin: `POST /api/tenant/bind` with `{ "spreadsheet_id": "<id>", "user_id": "<your user id>" }`.

## Safety invariants

- No global `SPREADSHEET_ID` fallback for multi-tenant user data.  
- Setup wizard (`/setup`) is **disabled** when `MULTI_TENANT=true`.  
- Unique `spreadsheet_id` per user (SQLite unique index + claim API).  
- Cache keys: `t:{user_id}:…`; jobs scoped per tenant; cron tick fans out.  
- Uploads: `uploads/{user_id}/{sha}.bin`.  
- Isolation tests: `backend/tests/test_tenant_isolation.py`.

## Single-tenant (unchanged)

Leave `MULTI_TENANT` unset/false. Existing `SPREADSHEET_ID` + `AUTH_MODE=dev` path works as before.
