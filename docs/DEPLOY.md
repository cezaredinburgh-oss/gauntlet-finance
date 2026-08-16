# Deploy Gauntlet Finance (beginner guide)

You will: **Google Sheets** (database) → **GitHub** (code) → **Railway or Render** (live HTTPS app).

The interactive wizard at **http://127.0.0.1:8020/setup** walks through the same steps.

## 0. Local prep

1. Install Python 3.12+, Node.js LTS, Git.
2. From the project folder:

```powershell
copy .env.example .env
python -m pip install -r backend\requirements.txt
$env:PYTHONPATH = "."
uvicorn backend.api.main:app --host 127.0.0.1 --port 8020
```

3. Open **http://127.0.0.1:8020/setup** and complete steps through **Prepare ledger**.

## 1. Google Sheets (already your cloud database)

- Upload a **service account JSON** key (Cloud Console).
- Prefer **Create spreadsheet automatically** in the wizard (or paste a sheet URL and share it as Editor with the service account email).
- Click **Prepare ledger** so tabs + categories exist.

Never commit `secrets/service-account.json` or `.env`.

## 2. GitHub

```powershell
.\scripts\Prepare-GitHub.ps1
```

Then create a repo on GitHub and push (commands are printed by the script).

Or:

```powershell
gh repo create gauntlet-finance --private --source=. --remote=origin --push
```

## 3. Railway (recommended)

1. https://railway.app → login with GitHub.
2. **New Project** → **Deploy from GitHub** → select `gauntlet-finance`.
3. Generate env vars:

```powershell
.\scripts\Export-DeploySecrets.ps1 "https://YOUR-APP.up.railway.app"
```

Or use wizard step **Deploy → Generate env vars**.

4. In Railway → **Variables**, paste each line (`KEY=value`).
5. Wait for deploy. Open `/health` — should show `"spreadsheet_configured": true`.
6. Open `/` for the UI.

### Required variables

| Variable | Source |
|----------|--------|
| `SPREADSHEET_ID` | From wizard / `.env` |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | One-line contents of the JSON key (paste from local `secrets/` — the API never returns the private key) |
| `SECRET_KEY` | Random string (wizard generates) |
| `CORS_ORIGINS` | Your public HTTPS origin (required in production; no `*` fallback) |
| `APP_ENV` | `production` |
| `AUTH_MODE` | Prefer `oauth` for public hosts. For trusted **single-user** SA deploys only: `dev` **and** `ALLOW_OPEN_AUTH=true` |
| `ALLOW_OPEN_AUTH` | `true` only with `AUTH_MODE=dev` on a private/trusted host. Omit (or `false`) with `oauth` |
| `REQUIRE_SHEETS` | `true` |

**Auth note:** Production refuses open API access when `AUTH_MODE` is `dev` or `disabled` unless `ALLOW_OPEN_AUTH=true`. Without that flag unauthenticated domain routes return **401** (login required). Prefer owner password, OAuth, or one-click demos on public domains — never leave `ALLOW_OPEN_AUTH=true` on a shared URL.

**Lab account:** optional tester that signs in with `LAB_EMAIL` / `LAB_PASSWORD` like a normal user. Ledger is `DiskBackedSheetsRepository` on the Railway volume (`/data/lab` when `/data` is mounted; or set `LAB_DATA_DIR=/data/lab`). Invited Google users stay on their own Sheets — they never share this JSON. Do not set `LAB_DATA_DIR` on iCloud/OneDrive.

Wipe the **host you are signed into** (in-process, so Railway hits the volume): Settings → Wipe lab ledger, or `POST /api/lab/reset` with `{ "confirm": "WIPE LAB" }`. A Windows CLI reset does not empty the Railway volume.

**Grok+:** set `AI_ENABLED=true` and `XAI_API_KEY` on the host (never commit the key). Lab/sandbox can fall back to local heuristics if the key is missing; real leftover Grok+ matching needs the key.

### Public demos (marketing)

| Variable | Effect |
|----------|--------|
| `DEMO_TOUR_ENABLED=true` | Landing **Explore sample portfolio** — synthetic data, read-only |
| `DEMO_SANDBOX_ENABLED=true` | Landing **Try with your statements** — empty session ledger, wiped on sign-out |
| `DEMO_SANDBOX_MAX_ACTIVE` | Optional cap on concurrent sandboxes (default 50) |
| Legacy `DEMO_LOGIN_*` | Optional password form; prefer one-click flags above |

Neither demo path uses the production Google Sheet.

### Multi-tenant production (personal account + invites)

When `MULTI_TENANT=true` on a public host:

| Variable | Notes |
|----------|--------|
| `MULTI_TENANT` | `true` |
| `AUTH_MODE` | **Must be `oauth`** in production or the process refuses to start |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth Web client |
| `OAUTH_REDIRECT_URI` | `https://<public-host>/api/auth/callback` |
| `PLATFORM_ADMIN_EMAILS` | Your Google email(s), comma-separated |
| `CONTROL_DB_PATH` | e.g. `/data/gauntlet_control.db` **on a Railway volume** |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Still required for live Sheets |
| `SPREADSHEET_ID` | Keep temporarily to use **Bind env SPREADSHEET_ID** migration; not used for user data after bind |
| `OWNER_*` | Owner password login is **disabled** under multi-tenant |
| Demo vars | Optional; demo stays on isolated memory |

Full cutover runbook (bind existing ledger, do not provision empty): see **`docs/MULTI_TENANT.md`** → *Migration of an existing single-user sheet*.

## 4. Render (alternative)

Use `render.yaml` or create a **Web Service** with Dockerfile from this repo. Same env vars as Railway.

## 5. Phone / tablet

Use the **HTTPS** URL Railway/Render gives you. Prefer locking the site later with Cloudflare Access if the URL is public.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `spreadsheet_configured: false` | Set `SPREADSHEET_ID` on the host |
| 403 / permission | Share sheet Editor with service account email |
| Blank UI | Check Docker build built `frontend/dist`; open browser console |
| CORS errors | Set `CORS_ORIGINS` to exact public origin (https, no trailing slash) |

## Local vs cloud

| | Local | Cloud |
|--|-------|-------|
| Start | `Start-App.bat` | Railway auto |
| UI | http://localhost:5190 | same origin as API |
| Data | Google Sheets | **same** Google Sheets |
