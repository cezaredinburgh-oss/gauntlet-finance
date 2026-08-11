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

**Auth note:** Production refuses open API access when `AUTH_MODE` is `dev` or `disabled` unless `ALLOW_OPEN_AUTH=true`. Without that flag the API returns **503** on authenticated routes.

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
