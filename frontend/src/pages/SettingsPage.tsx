import { useCallback, useEffect, useState } from "react";
import { ExternalLink, Save, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type {
  AdminJob,
  CleanupPreview,
  CleanupResult,
  Health,
  SheetsStatus,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageLoader, Spinner } from "../components/Spinner";

const STORAGE_KEY = "cf_ui_settings";

type UiSettings = {
  primaryCurrency: string;
  secondaryCurrency: string;
};

function loadUi(): UiSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as UiSettings;
  } catch {
    /* ignore */
  }
  return { primaryCurrency: "USD", secondaryCurrency: "CZK" };
}

export function SettingsPage() {
  const { user, isDevMode, logout } = useAuth();
  const [ui, setUi] = useState<UiSettings>(loadUi);
  const [saved, setSaved] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [sheets, setSheets] = useState<SheetsStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cleanup, setCleanup] = useState<CleanupPreview | null>(null);
  const [selectedScopes, setSelectedScopes] = useState<string[]>([]);
  const [confirmText, setConfirmText] = useState("");
  const [cleanupBusy, setCleanupBusy] = useState(false);
  const [cleanupResult, setCleanupResult] = useState<CleanupResult | null>(null);
  const [cleanupError, setCleanupError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<AdminJob[]>([]);
  const [jobKinds, setJobKinds] = useState<string[]>([]);
  const [jobBusy, setJobBusy] = useState<string | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [jobMsg, setJobMsg] = useState<string | null>(null);

  const refreshCleanupPreview = useCallback(async () => {
    try {
      const p = await api.cleanupPreview();
      setCleanup(p);
      setCleanupError(null);
    } catch (e) {
      setCleanupError(e instanceof Error ? e.message : "Cleanup preview failed");
    }
  }, []);

  const refreshJobs = useCallback(async () => {
    try {
      const j = await api.adminJobs(12);
      setJobs(j.items || []);
      setJobKinds(j.kinds || []);
      setJobError(null);
    } catch (e) {
      setJobError(e instanceof Error ? e.message : "Jobs list failed");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [h, s] = await Promise.all([api.health(), api.sheetsStatus()]);
        if (!cancelled) {
          setHealth(h);
          setSheets(s);
        }
        try {
          const p = await api.cleanupPreview();
          if (!cancelled) setCleanup(p);
        } catch {
          /* optional if older API */
        }
        try {
          const j = await api.adminJobs(12);
          if (!cancelled) {
            setJobs(j.items || []);
            setJobKinds(j.kinds || []);
          }
        } catch {
          /* optional */
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function startJob(kind: string) {
    setJobBusy(kind);
    setJobError(null);
    setJobMsg(null);
    try {
      const started = await api.startAdminJob(kind, { max_passes: 5 });
      setJobMsg(`Started ${kind} · ${started.job_id.slice(0, 8)}…`);
      // Poll a few times for quick feedback
      for (let i = 0; i < 40; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const job = await api.adminJob(started.job_id);
        if (job.status === "done" || job.status === "error") {
          setJobMsg(
            job.status === "done"
              ? `${kind} finished`
              : `${kind} failed: ${job.error || "error"}`,
          );
          break;
        }
      }
      await refreshJobs();
    } catch (e) {
      setJobError(e instanceof Error ? e.message : "Start job failed");
    } finally {
      setJobBusy(null);
    }
  }

  function toggleScope(id: string) {
    setSelectedScopes((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
    setCleanupResult(null);
  }

  async function runCleanup() {
    if (!cleanup || selectedScopes.length === 0) return;
    if (confirmText !== cleanup.confirm_token) return;
    setCleanupBusy(true);
    setCleanupError(null);
    setCleanupResult(null);
    try {
      const r = await api.cleanupRun(selectedScopes, confirmText);
      setCleanupResult(r);
      setConfirmText("");
      setSelectedScopes([]);
      await refreshCleanupPreview();
    } catch (e) {
      setCleanupError(e instanceof Error ? e.message : "Cleanup failed");
    } finally {
      setCleanupBusy(false);
    }
  }

  function saveUi() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(ui));
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  if (loading) return <PageLoader label="Loading settings…" />;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-sm text-ink-muted">Display preferences and backend connection</p>
      </div>

      {error && (
        <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      )}

      <section className="card space-y-4 p-5">
        <h2 className="text-sm font-semibold">Account</h2>
        <div className="flex items-center gap-3">
          {user?.picture ? (
            <img src={user.picture} alt="" className="h-12 w-12 rounded-full" />
          ) : (
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-brand/20 text-brand font-semibold">
              {(user?.name || user?.email || "?").slice(0, 1).toUpperCase()}
            </div>
          )}
          <div>
            <div className="font-medium">{user?.name || "Signed in"}</div>
            <div className="text-sm text-ink-muted">{user?.email}</div>
            <div className="text-xs text-ink-faint">
              Auth mode: {user?.auth_mode}
              {isDevMode ? " (local / service account)" : ""}
            </div>
          </div>
        </div>
        <button type="button" className="btn-secondary" onClick={() => void logout()}>
          Sign out
        </button>
      </section>

      <section className="card space-y-4 p-5">
        <h2 className="text-sm font-semibold">Display currencies</h2>
        <p className="text-xs text-ink-muted">
          Primary is emphasized; secondary appears as smaller gray text. Matching backend defaults
          (USD / CZK).
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label">Primary</label>
            <select
              className="input"
              value={ui.primaryCurrency}
              onChange={(e) => setUi((u) => ({ ...u, primaryCurrency: e.target.value }))}
            >
              <option value="USD">USD</option>
              <option value="CZK">CZK</option>
              <option value="EUR">EUR</option>
            </select>
          </div>
          <div>
            <label className="label">Secondary</label>
            <select
              className="input"
              value={ui.secondaryCurrency}
              onChange={(e) => setUi((u) => ({ ...u, secondaryCurrency: e.target.value }))}
            >
              <option value="CZK">CZK</option>
              <option value="USD">USD</option>
              <option value="EUR">EUR</option>
            </select>
          </div>
        </div>
        <button type="button" className="btn-primary" onClick={saveUi}>
          <Save className="h-4 w-4" />
          {saved ? "Saved" : "Save preferences"}
        </button>
      </section>

      <section className="card space-y-3 p-5">
        <h2 className="text-sm font-semibold">Linked Google Spreadsheet</h2>
        {sheets ? (
          <>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between gap-4">
                <dt className="text-ink-muted">Backend</dt>
                <dd className="font-medium">{sheets.backend}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-ink-muted">Spreadsheet ID</dt>
                <dd className="max-w-[60%] break-all text-right font-mono text-xs">
                  {sheets.spreadsheet_id || "— (in-memory)"}
                </dd>
              </div>
              {sheets.service_account_email && (
                <div className="flex justify-between gap-4">
                  <dt className="text-ink-muted">Service account</dt>
                  <dd className="max-w-[60%] break-all text-right text-xs">
                    {sheets.service_account_email}
                  </dd>
                </div>
              )}
              <div className="flex justify-between gap-4">
                <dt className="text-ink-muted">Status</dt>
                <dd className={sheets.ok !== false ? "text-ok" : "text-warn"}>
                  {sheets.message || (sheets.ok ? "OK" : "Check setup")}
                </dd>
              </div>
            </dl>
            {sheets.spreadsheet_id && (
              <a
                className="btn-secondary inline-flex"
                href={`https://docs.google.com/spreadsheets/d/${sheets.spreadsheet_id}/edit`}
                target="_blank"
                rel="noreferrer"
              >
                Open in Google Sheets <ExternalLink className="h-4 w-4" />
              </a>
            )}
            <a className="btn-ghost inline-flex text-sm" href="/setup" target="_blank" rel="noreferrer">
              Backend setup wizard
            </a>
          </>
        ) : (
          <EmptyState title="No sheet status" description="Is the API running?" />
        )}
      </section>

      <section className="card space-y-2 p-5 text-sm">
        <h2 className="text-sm font-semibold">API health</h2>
        {health ? (
          <ul className="text-ink-muted">
            <li>Status: {health.status}</li>
            <li>App: {health.app}</li>
            <li>Auth: {health.auth_mode}</li>
            <li>Spreadsheet configured: {health.spreadsheet_configured ? "yes" : "no"}</li>
          </ul>
        ) : (
          <Spinner />
        )}
      </section>

      <section className="card space-y-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold">Maintenance jobs</h2>
            <p className="text-xs text-ink-muted">
              Background FX maintenance (CNB rates + amount_usd / amount_czk). Safe to re-run;
              one job of each kind at a time.
            </p>
          </div>
          <button type="button" className="btn-ghost text-xs" onClick={() => void refreshJobs()}>
            Refresh
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          {(jobKinds.length
            ? jobKinds
            : ["fx-full", "fx-fetch-cnb", "fx-backfill-amounts"]
          ).map((kind) => (
            <button
              key={kind}
              type="button"
              className="btn-secondary text-xs"
              disabled={jobBusy != null}
              onClick={() => void startJob(kind)}
            >
              {jobBusy === kind ? <Spinner className="h-3.5 w-3.5" /> : null}
              {kind}
            </button>
          ))}
        </div>
        {jobMsg && <p className="text-xs text-ok">{jobMsg}</p>}
        {jobError && (
          <p className="text-xs text-danger">{jobError}</p>
        )}
        {jobs.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-white/10">
            <table className="w-full text-left text-xs">
              <thead className="text-ink-faint">
                <tr>
                  <th className="px-2 py-1.5 font-medium">Kind</th>
                  <th className="px-2 py-1.5 font-medium">Status</th>
                  <th className="px-2 py-1.5 font-medium">Started</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id} className="border-t border-white/5">
                    <td className="px-2 py-1.5 font-mono">{j.kind}</td>
                    <td className="px-2 py-1.5">
                      <span
                        className={
                          j.status === "done"
                            ? "text-ok"
                            : j.status === "error"
                              ? "text-danger"
                              : j.status === "running"
                                ? "text-brand"
                                : "text-ink-muted"
                        }
                      >
                        {j.status}
                      </span>
                      {j.error ? (
                        <span className="ml-1 text-danger">· {j.error}</span>
                      ) : null}
                    </td>
                    <td className="px-2 py-1.5 text-ink-faint">
                      {(j.started_at || "").replace("T", " ").slice(0, 19)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card space-y-4 border border-danger/25 p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-danger">Data cleanup</h2>
            <p className="mt-1 text-xs text-ink-muted">
              Permanently deletes rows in Google Sheets for the selected areas. Re-import from{" "}
              <span className="font-medium text-ink">Bank statements/</span> afterward. Type{" "}
              <span className="font-mono text-danger">DELETE</span> to confirm.
            </p>
          </div>
          <button
            type="button"
            className="btn-ghost text-xs"
            onClick={() => void refreshCleanupPreview()}
            disabled={cleanupBusy}
          >
            Refresh counts
          </button>
        </div>

        {cleanupError && (
          <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {cleanupError}
          </div>
        )}

        {cleanupResult && (
          <div className="rounded-xl border border-ok/30 bg-ok/10 px-3 py-2 text-sm text-ok">
            Cleared:{" "}
            {Object.entries(cleanupResult.tabs_cleared)
              .map(([t, n]) => `${t} (${n})`)
              .join(", ") || "nothing"}
            {cleanupResult.transactions_uncategorized
              ? ` · uncategorized ${cleanupResult.transactions_uncategorized} txs`
              : ""}
          </div>
        )}

        {!cleanup ? (
          <p className="text-xs text-ink-faint">
            Cleanup API not available (restart the API if you just updated).
          </p>
        ) : (
          <>
            <ul className="space-y-2">
              {cleanup.scopes.map((s) => (
                <li
                  key={s.id}
                  className="flex items-start gap-3 rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2"
                >
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={selectedScopes.includes(s.id)}
                    onChange={() => toggleScope(s.id)}
                    disabled={cleanupBusy}
                    id={`cleanup-${s.id}`}
                  />
                  <label htmlFor={`cleanup-${s.id}`} className="min-w-0 flex-1 cursor-pointer">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="text-sm font-medium">{s.label}</span>
                      <span className="font-mono text-xs text-ink-faint">{s.total_rows} rows</span>
                    </div>
                    <p className="text-xs text-ink-muted">{s.description}</p>
                    {s.notes ? <p className="mt-0.5 text-xs text-warn">{s.notes}</p> : null}
                    <p className="mt-0.5 font-mono text-[10px] text-ink-faint">
                      {Object.entries(s.row_counts)
                        .map(([t, n]) => `${t}:${n}`)
                        .join(" · ")}
                    </p>
                  </label>
                </li>
              ))}
            </ul>

            <div>
              <label className="label">Type DELETE to confirm</label>
              <input
                className="input font-mono"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder={cleanup.confirm_token}
                disabled={cleanupBusy}
                autoComplete="off"
              />
            </div>

            <button
              type="button"
              className="btn-primary bg-danger hover:bg-danger/90 disabled:opacity-40"
              disabled={
                cleanupBusy ||
                selectedScopes.length === 0 ||
                confirmText !== cleanup.confirm_token
              }
              onClick={() => void runCleanup()}
            >
              {cleanupBusy ? <Spinner className="border-t-white" /> : <Trash2 className="h-4 w-4" />}
              {cleanupBusy ? "Deleting…" : "Delete selected data"}
            </button>
          </>
        )}
      </section>
    </div>
  );
}
