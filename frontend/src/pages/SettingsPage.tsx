import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ExternalLink, Save, Trash2 } from "lucide-react";
import { api, setupWizardUrl } from "../api/client";
import type {
  AdminJob,
  AiStatus,
  CleanupPreview,
  CleanupResult,
  Health,
  SheetsStatus,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, PageLoader, Spinner } from "../components/Spinner";
import { onboardingPath } from "../lib/onboarding";

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
  const { user, isDevMode, logout, refresh, isReadOnly } = useAuth();
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
  const [exportYear, setExportYear] = useState(() => new Date().getFullYear());
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);
  const [aiStatusError, setAiStatusError] = useState<string | null>(null);

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
        try {
          const a = await api.aiStatus();
          if (!cancelled) {
            setAiStatus(a);
            setAiStatusError(null);
          }
        } catch (e) {
          if (!cancelled) {
            setAiStatus(null);
            setAiStatusError(
              e instanceof Error ? e.message : "AI status unavailable",
            );
          }
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

      <section className="card space-y-3 p-5">
        <h2 className="text-sm font-semibold">Grok AI assist</h2>
        <p className="text-xs text-ink-muted">
          Categorize + unknown cash CSV mapping. Platform uses a server xAI key;
          the writable sandbox demo also works offline with a local heuristic when
          no key is set. Nothing is applied until you confirm.
        </p>
        {aiStatusError && (
          <p className="text-xs text-danger">{aiStatusError}</p>
        )}
        {aiStatus && (
          <dl className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <dt className="text-ink-faint">Mode</dt>
              <dd className="font-medium text-ink">{aiStatus.mode}</dd>
            </div>
            <div>
              <dt className="text-ink-faint">Configured</dt>
              <dd className="font-medium text-ink">
                {aiStatus.configured ? "Yes" : "No"}
              </dd>
            </div>
            <div>
              <dt className="text-ink-faint">Model</dt>
              <dd className="font-medium text-ink">{aiStatus.model || "—"}</dd>
            </div>
            <div>
              <dt className="text-ink-faint">Daily quota</dt>
              <dd className="font-medium tabular-nums text-ink">
                {aiStatus.quota_used}/{aiStatus.quota_cap} tokens
              </dd>
            </div>
          </dl>
        )}
        {aiStatus?.sandbox_fallback && (
          <p className="rounded-lg border border-brand/25 bg-brand/10 px-2.5 py-1.5 text-[11px] text-ink-muted">
            Sandbox demo AI is active (local heuristics, no Grok API key). Real Grok
            needs <code className="text-ink-muted">AI_ENABLED=true</code> and{" "}
            <code className="text-ink-muted">XAI_API_KEY</code>.
          </p>
        )}
        {!aiStatus?.configured && !aiStatusError && (
          <p className="text-[11px] text-ink-faint">
            To enable real Grok: set <code className="text-ink-muted">AI_ENABLED=true</code>{" "}
            and <code className="text-ink-muted">XAI_API_KEY</code> in the API{" "}
            <code className="text-ink-muted">.env</code>, then restart. Sandbox demos
            still get Map/Suggest via fallback when{" "}
            <code className="text-ink-muted">AI_SANDBOX_FALLBACK</code> is on (default).
          </p>
        )}
      </section>

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
              {user?.is_demo ? " · demo" : ""}
              {user?.role ? ` · role: ${user.role}` : ""}
            </div>
          </div>
        </div>
        <button type="button" className="btn-secondary" onClick={() => void logout()}>
          Sign out
        </button>
      </section>

      {user?.role === "platform_admin" && user.multi_tenant && (
        <>
          <AdminLegacySheetSection
            tenantReady={Boolean(user.tenant_ready || user.spreadsheet_bound)}
            onBound={() => void refresh()}
          />
          <AdminInvitesSection />
        </>
      )}

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
            <div className="flex flex-wrap gap-2">
              <Link className="btn-primary inline-flex text-sm" to={onboardingPath()}>
                New-user setup path
              </Link>
              <Link
                className="btn-secondary inline-flex text-sm"
                to={onboardingPath({ preview: true })}
              >
                Preview new-user path
              </Link>
              {!(health?.multi_tenant) && (
                <a
                  className="btn-secondary inline-flex text-sm"
                  href={setupWizardUrl()}
                  target="_blank"
                  rel="noreferrer"
                >
                  Sheets wizard only
                  <ExternalLink className="h-4 w-4" />
                </a>
              )}
            </div>
            <p className="text-xs text-ink-faint">
              {health?.multi_tenant
                ? "Multi-tenant: use setup → Provision ledger (the global /setup wizard is disabled). Preview walks the UI without writes."
                : "Full path: welcome, Sheets, statements, rules. Preview walks the UI without changing your live connection or ledger."}
            </p>
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

      <section className="card space-y-3 p-5">
        <h2 className="text-sm font-semibold">Year-end export pack</h2>
        <p className="text-xs text-ink-muted">
          ZIP with tax report JSON/CSV, open lots, multi-year realised gains, category spend, and
          statement-file audit. Not tax advice.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="input w-auto"
            value={exportYear}
            onChange={(e) => setExportYear(Number(e.target.value))}
          >
            {Array.from({ length: 8 }, (_, i) => new Date().getFullYear() - i).map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
          <a className="btn-primary text-sm" href={api.yearEndExportUrl(exportYear)}>
            Download ZIP
          </a>
        </div>
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

      {!isReadOnly && (
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
      )}
    </div>
  );
}

type InviteRow = {
  id: string;
  email: string;
  pending?: boolean;
  accepted_at?: string | null;
  created_at?: string;
};

type TenantUserRow = {
  id: string;
  email: string;
  role: string;
  tenant_ready?: boolean;
  spreadsheet_id?: string | null;
};

/**
 * Platform admin: migrate legacy single-tenant sheet onto a control-plane user.
 * Prefer "Bind env sheet to me" over Provision (which creates an empty ledger).
 */
function AdminLegacySheetSection({
  tenantReady,
  onBound,
}: {
  tenantReady: boolean;
  onBound: () => void;
}) {
  const [sheetId, setSheetId] = useState("");
  const [targetUserId, setTargetUserId] = useState("");
  const [users, setUsers] = useState<TenantUserRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const loadUsers = useCallback(async () => {
    try {
      const us = await api.listTenantUsers();
      setUsers(
        (us.items || []).map((u) => ({
          id: String(u.id ?? ""),
          email: String(u.email ?? ""),
          role: String(u.role ?? "user"),
          tenant_ready: Boolean(u.tenant_ready),
          spreadsheet_id: (u.spreadsheet_id as string | null | undefined) ?? null,
        })),
      );
    } catch {
      /* invites section may surface the same failure */
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  async function bindEnvToMe() {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const r = await api.migrateEnvSheet();
      setMsg(
        r.status === "already_bound"
          ? `Already bound to ${r.spreadsheet_id ?? "sheet"}.`
          : `Bound env sheet ${r.spreadsheet_id ?? ""} to your account.`,
      );
      await loadUsers();
      onBound();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Migrate failed");
    } finally {
      setBusy(false);
    }
  }

  async function bindExplicit(e: React.FormEvent) {
    e.preventDefault();
    if (!sheetId.trim()) return;
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const r = await api.tenantBind(
        sheetId.trim(),
        targetUserId.trim() || undefined,
      );
      setMsg(`Bound ${r.spreadsheet_id ?? sheetId.trim()} successfully.`);
      setSheetId("");
      await loadUsers();
      onBound();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bind failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card space-y-4 p-5">
      <div>
        <h2 className="text-sm font-semibold text-brand">Admin · Legacy sheet</h2>
        <p className="mt-1 text-xs text-ink-muted">
          Attach an existing Google Sheet to a user after multi-tenant cutover. Do{" "}
          <strong className="text-ink">not</strong> use Provision ledger if you want to keep
          historical data — that creates a new empty sheet.
        </p>
        {tenantReady ? (
          <p className="mt-2 text-xs text-ok">Your account already has a sheet bound.</p>
        ) : (
          <p className="mt-2 text-xs text-warn">
            Your account has no sheet yet — bind the legacy production id before using the app.
          </p>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={busy}
          onClick={() => void bindEnvToMe()}
        >
          {busy ? <Spinner /> : null}
          Bind env SPREADSHEET_ID to me
        </button>
      </div>

      <form className="space-y-3" onSubmit={(e) => void bindExplicit(e)}>
        <div>
          <label className="label" htmlFor="legacy-sheet-id">
            Spreadsheet ID or Google Sheets URL
          </label>
          <input
            id="legacy-sheet-id"
            className="input w-full"
            type="text"
            placeholder="1BxiM… or https://docs.google.com/spreadsheets/d/…"
            value={sheetId}
            onChange={(e) => setSheetId(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div>
          <label className="label" htmlFor="legacy-target-user">
            Target user (optional — default: you)
          </label>
          <select
            id="legacy-target-user"
            className="input w-full"
            value={targetUserId}
            onChange={(e) => setTargetUserId(e.target.value)}
          >
            <option value="">Myself (signed-in admin)</option>
            {users
              .filter((u) => u.id)
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.email}
                  {u.tenant_ready ? " · ready" : " · no sheet"}
                  {u.role === "platform_admin" ? " · admin" : ""}
                </option>
              ))}
          </select>
        </div>
        <button type="submit" className="btn-secondary" disabled={busy || !sheetId.trim()}>
          {busy ? <Spinner /> : null}
          Bind spreadsheet
        </button>
      </form>

      {msg && <p className="text-sm text-ok">{msg}</p>}
      {error && <p className="text-sm text-danger">{error}</p>}
    </section>
  );
}

function AdminInvitesSection() {
  const [email, setEmail] = useState("");
  const [items, setItems] = useState<InviteRow[]>([]);
  const [users, setUsers] = useState<Array<{ email: string; role: string; tenant_ready?: boolean }>>(
    [],
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [inv, us] = await Promise.all([
        api.listInvites(false),
        api.listTenantUsers().catch(() => ({ items: [] })),
      ]);
      setItems((inv.items || []) as InviteRow[]);
      setUsers(
        (us.items || []).map((u) => ({
          email: String(u.email ?? ""),
          role: String(u.role ?? "user"),
          tenant_ready: Boolean(u.tenant_ready),
        })),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load invites");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function createInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      await api.createInvite(email.trim());
      setMsg(`Invite created for ${email.trim()}`);
      setEmail("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invite failed");
    } finally {
      setBusy(false);
    }
  }

  async function removeInvite(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api.deleteInvite(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card space-y-4 p-5">
      <div>
        <h2 className="text-sm font-semibold text-brand">Admin · Invites</h2>
        <p className="mt-1 text-xs text-ink-muted">
          Platform admin only. Invite Google emails so they can sign in on this multi-tenant host.
        </p>
      </div>

      <form className="flex flex-wrap gap-2" onSubmit={(e) => void createInvite(e)}>
        <input
          className="input min-w-[12rem] flex-1"
          type="email"
          placeholder="user@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? <Spinner /> : null}
          Invite
        </button>
      </form>

      {msg && <p className="text-sm text-ok">{msg}</p>}
      {error && <p className="text-sm text-danger">{error}</p>}

      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Invites</h3>
        {items.length === 0 ? (
          <p className="mt-1 text-xs text-ink-muted">No invites yet.</p>
        ) : (
          <ul className="mt-2 space-y-1 text-sm">
            {items.map((i) => (
              <li
                key={i.id}
                className="flex items-center justify-between gap-2 rounded-lg border border-white/10 px-3 py-2"
              >
                <span>
                  {i.email}
                  <span className="ml-2 text-xs text-ink-faint">
                    {i.accepted_at ? "accepted" : "pending"}
                  </span>
                </span>
                {!i.accepted_at && (
                  <button
                    type="button"
                    className="btn-ghost text-xs"
                    disabled={busy}
                    onClick={() => void removeInvite(i.id)}
                  >
                    Revoke
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {users.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">Users</h3>
          <ul className="mt-2 space-y-1 text-xs text-ink-muted">
            {users.map((u) => (
              <li key={u.email}>
                {u.email} · {u.role}
                {u.tenant_ready ? " · ready" : " · no sheet"}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
