# Connect a real Google Sheet (beginner checklist)

**Recommended method: Service Account** (already supported).  
You create one robot Google identity, download a JSON key, and share your spreadsheet with that robot’s email. No browser OAuth dance, no expired user tokens, works from Windows + later from any device that hits your API.

## Easiest path: interactive wizard

```powershell
cd "C:\Users\cezar\iCloudDrive\Gauntlet Finance App"
.\.venv\Scripts\Activate.ps1   # if you use a venv
$env:PYTHONPATH = "."
uvicorn backend.api.main:app --reload --port 8020
```

Then open in your browser:

**http://localhost:8020/setup**

The wizard walks you through Cloud Console links, uploading the JSON key, pasting the Spreadsheet ID, sharing access, and creating all tabs.  
Or: `python -m backend.scripts.open_setup_wizard` (starts the server and opens the browser).

---

## What the backend already supports

| Method | Supported? | When used |
|---|---|---|
| **Service account** (JSON key) | **Yes** | `AUTH_MODE=dev` + `SPREADSHEET_ID` + `GOOGLE_APPLICATION_CREDENTIALS` |
| **OAuth 2.0 user login** | Yes | `AUTH_MODE=oauth` + `GOOGLE_CLIENT_ID` / `SECRET` + browser `/auth/login` |
| In-memory (no Google) | Yes | `AUTH_MODE=dev` and empty `SPREADSHEET_ID` |

**Env vars / files:**

| Name | Purpose |
|---|---|
| `SPREADSHEET_ID` | ID (or full URL) of your Google Spreadsheet |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service-account JSON (default `secrets/service-account.json`) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Optional: paste full JSON instead of a file |
| `AUTH_MODE` | `dev` (service account) or `oauth` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Only for OAuth mode |
| `secrets/service-account.json` | Downloaded key file (never commit this) |

There is **no** `token.json` for the service-account path.

---

## Step-by-step checklist (Service Account)

### A. Google Cloud project

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Sign in with **your** Google account (the one that will own the spreadsheet).
3. Top bar → project dropdown → **New Project**.
4. Name it e.g. `gauntlet-finance` → **Create**.
5. Select that project (confirm the name in the top bar).

### B. Enable APIs

1. Menu ☰ → **APIs & Services** → **Library**.
2. Search **Google Sheets API** → **Enable**.
3. Search **Google Drive API** → **Enable**  
   (Drive is optional for service-account access to a shared sheet, but recommended).

### C. Create a service account + JSON key

1. Menu ☰ → **APIs & Services** → **Credentials**.
2. **+ Create credentials** → **Service account**.
3. Service account name: `finance-sheets` (or any name).
4. Click **Create and continue** → skip optional roles → **Done**.
5. Click the new service account email in the list.
6. Tab **Keys** → **Add key** → **Create new key** → type **JSON** → **Create**.
7. A JSON file downloads automatically (name like `project-xxxx.json`).
8. On that same page, copy the **Email**  
   (`finance-sheets@YOUR-PROJECT.iam.gserviceaccount.com`).  
   You will share the spreadsheet with this email.

### D. Create and share the spreadsheet

1. Open [Google Sheets](https://sheets.google.com/) → **Blank** spreadsheet.
2. Rename it (top left), e.g. `Gauntlet Finance Data`.
3. From the browser URL copy the ID:
   ```
   https://docs.google.com/spreadsheets/d/  1abc...XYZ  /edit
                                          ^^^^^^^^^^^
                                          SPREADSHEET_ID
   ```
4. Click **Share** (top right).
5. Paste the **service account email** from step C.8.
6. Role: **Editor**.
7. Uncheck “Notify people” if you like → **Share** / **Send**.
8. Keep yourself as **Owner** (default).

### E. Put files into this project

1. In the project folder create `secrets` if needed:
   ```powershell
   mkdir secrets
   ```
2. Move/rename the downloaded JSON to:
   ```
   secrets\service-account.json
   ```
3. Copy env template and edit:
   ```powershell
   copy .env.example .env
   notepad .env
   ```
4. Set at least:
   ```env
   AUTH_MODE=dev
   SPREADSHEET_ID=1abc...XYZ
   GOOGLE_APPLICATION_CREDENTIALS=secrets/service-account.json
   SECRET_KEY=any-long-random-string-you-choose
   ```

**Do not commit** `.env` or `secrets/*.json` (they are gitignored).

### F. Create tabs automatically

From the project root:

```powershell
$env:PYTHONPATH = "."
python -m backend.scripts.setup_google_sheet
```

Optional seed (sample accounts/categories):

```powershell
python -m backend.scripts.setup_google_sheet --seed
```

You should see `[OK]` for each tab:  
Accounts, Transactions, InvestmentLots, InvestmentEvents, Categories, CategoryRules, FXRates, StatementFiles, Settings, Prices.

### G. Start the API and verify

```powershell
$env:PYTHONPATH = "."
uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8020
```

In another terminal:

```powershell
curl.exe -s http://localhost:8020/health
curl.exe -s http://localhost:8020/sheets/status
```

`/sheets/status` should show `"backend": "google_sheets"` and `"ok": true`.

Open http://localhost:8020/docs for interactive API.

---

## Windows commands (copy-paste summary)

```powershell
# 0) Go to project
cd "C:\Users\cezar\iCloudDrive\Gauntlet Finance App"

# 1) Virtualenv + packages
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt

# 2) Env + credentials (after Google Cloud steps)
mkdir secrets -Force
# place downloaded JSON as secrets\service-account.json
copy .env.example .env
# edit .env → SPREADSHEET_ID + paths

# 3) Create tabs
$env:PYTHONPATH = "."
python -m backend.scripts.setup_google_sheet

# 4) Start server
uvicorn backend.api.main:app --reload --port 8020

# 5) Verify (new terminal, venv activated)
curl.exe -s http://localhost:8020/health
curl.exe -s http://localhost:8020/sheets/status
```

Docker alternative (after `.env` + `secrets/` are ready):

```powershell
docker compose up --build
```

Mount credentials: put the JSON at `secrets/service-account.json` and set  
`GOOGLE_APPLICATION_CREDENTIALS=/secrets/service-account.json` in `.env` for containers,  
or keep path relative and add a volume (see `docker-compose.yml`).

---

## Troubleshooting (top 3)

### 1) “Google Sheets API has not been used” / 403 API not enabled  
**Cause:** Sheets API not enabled on the Cloud project.  
**Fix:** Cloud Console → APIs & Services → Library → enable **Google Sheets API** (and Drive). Wait 1–2 minutes, re-run setup.

### 2) Wrong Spreadsheet ID  
**Cause:** Typo, or copied the whole URL incorrectly.  
**Fix:** Open the sheet → copy only the segment between `/d/` and `/edit`.  
The app also accepts a full URL in `SPREADSHEET_ID`. Re-run setup; check `/sheets/status`.

### 3) Permission denied / “The caller does not have permission”  
**Cause:** Spreadsheet not shared with the **service account email** (the long `@...iam.gserviceaccount.com` address inside the JSON as `client_email`).  
**Fix:** Sheet → Share → paste that email → **Editor**.  
Run:
```powershell
python -c "from backend.sheets.google_sheets import service_account_email; print(service_account_email(json_path='secrets/service-account.json'))"
```
Share with whatever email it prints.

### Bonus: expired token  
Only applies to **OAuth** mode. Service accounts do not use user refresh tokens.  
If you use OAuth: visit `/auth/login` again, or switch to service account (`AUTH_MODE=dev`).

---

## Optional: OAuth instead of service account

Only if you prefer logging in as yourself in the browser:

1. Credentials → Create → **OAuth client ID** → Application type **Web application**.
2. Redirect URI: `http://localhost:8020/auth/callback`.
3. Put Client ID/Secret in `.env`, set `AUTH_MODE=oauth`.
4. Still set `SPREADSHEET_ID`.
5. Open http://localhost:8020/auth/login and approve Sheets access.

For a personal multi-device app, **service account is simpler**.

