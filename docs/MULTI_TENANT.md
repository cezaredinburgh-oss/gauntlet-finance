# Multi-tenant SaaS (W1–W5 foundation)

Gauntlet can run as **single-tenant** (default, personal app) or **multi-tenant SaaS**
(invite-only Google OAuth, one Google Sheet / memory ledger per user).

## Enable

```env
MULTI_TENANT=true
AUTH_MODE=oauth
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
OAUTH_REDIRECT_URI=https://your-api/api/auth/callback
SECRET_KEY=<long-random>
PLATFORM_ADMIN_EMAILS=you@example.com
CONTROL_DB_PATH=/data/gauntlet_control.db   # optional; defaults under data/
# Live Sheets (production multi-tenant):
GOOGLE_APPLICATION_CREDENTIALS=secrets/service-account.json
# Local / tests without Google:
MULTI_TENANT_MEMORY_SHEETS=true
REPO_BACKEND=memory
```

**Never** set `ALLOW_OPEN_AUTH=true` for multi-tenant production — open auth is refused even if set.

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

## User lifecycle

1. Admin invites email.  
2. User completes Google OAuth (`/api/auth/login`).  
3. Uninvited Google accounts are redirected with `auth_error=not_invited` (no session).  
4. `POST /api/tenant/provision` creates/binds spreadsheet (memory or Google).  
5. Domain APIs use **only** that user’s ledger.

## Migration of an existing single-user sheet

1. Enable multi-tenant + control DB.  
2. Set your email in `PLATFORM_ADMIN_EMAILS`.  
3. Log in with OAuth (or seed user via control store).  
4. `POST /api/tenant/bind` with `{ "spreadsheet_id": "<your existing id>" }`.

## Safety invariants

- No global `SPREADSHEET_ID` fallback for multi-tenant user data.  
- Setup wizard (`/setup`) is **disabled** when `MULTI_TENANT=true`.  
- Cache keys: `t:{user_id}:…`.  
- Uploads: `uploads/{user_id}/{sha}.bin`.  
- Isolation tests: `backend/tests/test_tenant_isolation.py`.

## Single-tenant (unchanged)

Leave `MULTI_TENANT` unset/false. Existing `SPREADSHEET_ID` + `AUTH_MODE=dev` path works as before.
