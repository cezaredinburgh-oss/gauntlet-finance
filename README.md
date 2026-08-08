# Gauntlet Finance App

Personal multi-currency finance app: **statements-only** ledger (bank/broker files), Google Sheets storage, FIFO lots with Czech 3-year tax tracking, dark glass UI.

| Service | Port | Bind |
|---------|------|------|
| API (FastAPI) | **8020** | `127.0.0.1` |
| UI (Vite/React) | **5190** | `127.0.0.1` |

> Ports avoid clash with Collective (8010/5180) and common defaults (8000/5173).

## Data source rule (hard)

All bank / broker transaction and holdings data must come only from files in:

`Bank statements/`

(or test fixtures). **Do not** import ledgers from external portfolio desk apps. Market prices (yfinance) and CNB FX rates are allowed separately.

## Quick start (Windows)

1. Install **Python 3.12+** and **Node.js LTS**.
2. Copy env template and install backend deps:

```powershell
cd "C:\Users\cezar\iCloudDrive\Gauntlet Finance App"
copy .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

3. (Optional) Google Sheets: put service-account JSON in `secrets/service-account.json`, set `SPREADSHEET_ID` in `.env`, share the sheet Editor to the service account email. See design `docs/GAUNTLET_DESIGN.md` and Collective’s Sheets setup docs for reference.

4. Double-click **`Start-App.bat`**.  
   - The console closes immediately (no leftover windows).  
   - API + UI run **hidden**; only the browser should appear.  
   - App: http://localhost:5190  
   - API health: http://127.0.0.1:8020/health  
   - Logs: `launcher.log`, `api.err.log`, `ui.err.log`  
   - On failure: a popup + those log files  

5. Stop: double-click **`Stop-App.bat`** (also leaves no console).

### Manual run

```powershell
# Terminal 1 — API
$env:PYTHONPATH = "."
uvicorn backend.api.main:app --reload --host 127.0.0.1 --port 8020

# Terminal 2 — UI
cd frontend
npm install
npm run dev
```

## Money & types

- All money uses **Decimal** in Python; API money fields are **strings** (never JSON floats).
- Display: **USD** primary, **CZK** secondary (hover/tooltip).

## Project layout

```
backend/          # FastAPI, parsers, engines, services, sheets, tests
frontend/         # React + Vite
docs/             # GAUNTLET_DESIGN.md, BUILD_LOG.md, reviews
Bank statements/  # Statement fixtures / exports
secrets/          # gitignored service account
```

## Development status

- **Phase 0 design:** `docs/GAUNTLET_DESIGN.md` (approved, 0 open review issues)
- **PR1:** scaffold (this README, health, UI shell, Start-App)
- Further PRs: schema → FX → engines → parsers → Sheets → import → UI pages — see design **PR Plan**

## Tests

```powershell
$env:PYTHONPATH = "."
pytest backend/tests -q
```

Frontend:

```powershell
cd frontend
npm run lint
npm run build
```

## Non-negotiables (summary)

- Statements-only ledger; no external portfolio imports  
- Internal transfers never income/expense  
- Revolut crypto fee-net Buys; Digital Assets Europe → crypto pot  
- Czech 1095-day exemption on open lots  
- Fitness + My business categories (seeded in PR2+)  

Full design: [`docs/GAUNTLET_DESIGN.md`](docs/GAUNTLET_DESIGN.md)

## Setup wizard (Sheets + GitHub + deploy)

1. Start the API: `uvicorn backend.api.main:app --host 127.0.0.1 --port 8020` (with `PYTHONPATH=.`).
2. Open **http://127.0.0.1:8020/setup** — guided Google Cloud key, create spreadsheet, prepare ledger, GitHub, Railway.
3. Or: `python -m backend.scripts.open_setup_wizard`
4. Deploy guide: [docs/DEPLOY.md](docs/DEPLOY.md)

