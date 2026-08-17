import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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
import { SETTINGS_DESK } from "../auth/labDesk";
import { EmptyState, PageLoader, Spinner } from "../components/Spinner";
import { AdminInvitesSection } from "../features/settings-next/AdminInvitesSection";
import { AdminLegacySheetSection } from "../features/settings-next/AdminLegacySheetSection";
import { SettingsJumpNav } from "../features/settings-next/SettingsJumpNav";
import { SettingsSection } from "../features/settings-next/SettingsSection";
import { LabNextChrome } from "../lab-chrome/LabNextChrome";
import { onboardingPath, resetEmptyLabClientState } from "../lib/onboarding";

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

/** Lab next Settings: jump-nav sections. Same fetch/mutations as classic. */
export function SettingsPageNext() {
  const { user, isDevMode, logout, refresh, isReadOnly } = useAuth();
  const navigate = useNavigate();
  const [labWipeConfirm, setLabWipeConfirm] = useState("");
  const [labWipeBusy, setLabWipeBusy] = useState(false);
  const [labWipeError, setLabWipeError] = useState<string | null>(null);
  const [labWipeMsg, setLabWipeMsg] = useState<string | null>(null);
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

  // Same key as classic; nothing else reads it — display preference only, no FX.
  function saveUi() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(ui));
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  const showLabWipe = user?.demo_kind === "lab";

  return (
    <LabNextChrome config={SETTINGS_DESK} label="Settings desk">
      {loading ? (
        <PageLoader label="Loading settings…" />
      ) : (
        <div className="mx-auto max-w-2xl min-w-0 space-y-6">
          <SettingsJumpNav />

          {error && (
            <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-pretty break-words text-sm text-danger">
              {error}
            </div>
          )}

          <SettingsSection id="account" title="Account">
            <div className="flex min-w-0 items-center gap-3">
              {user?.picture ? (
                <img src={user.picture} alt="" className="h-12 w-12 shrink-0 rounded-full" />
              ) : (
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-brand/20 font-semibold text-brand">
                  {(user?.name || user?.email || "?").slice(0, 1).toUpperCase()}
                </div>
              )}
              <div className="min-w-0">
                <div className="text-pretty break-words font-medium">{user?.name || "Signed in"}</div>
                <div className="text-pretty break-words text-sm text-ink-muted">{user?.email}</div>
                <div className="text-pretty break-words text-xs text-ink-faint">
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
          </SettingsSection>

          <SettingsSection id="display" title="Display">
            <p className="text-pretty break-words text-xs text-ink-muted">
              Display preference only — does not convert history.
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
          </SettingsSection>

          <SettingsSection id="storage" title="Storage">
            {sheets ? (
              <>
                <dl className="space-y-2 text-sm">
                  <div className="flex justify-between gap-4">
                    <dt className="text-ink-muted">Backend</dt>
                    <dd className="min-w-0 break-words font-medium">{sheets.backend}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="shrink-0 text-ink-muted">Spreadsheet ID</dt>
                    <dd className="max-w-[60%] break-all text-right font-mono text-xs">
                      {sheets.spreadsheet_id || "— (in-memory)"}
                    </dd>
                  </div>
                  {sheets.service_account_email && (
                    <div className="flex justify-between gap-4">
                      <dt className="shrink-0 text-ink-muted">Service account</dt>
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
                <p className="text-pretty break-words text-xs text-ink-faint">
                  {health?.multi_tenant
                    ? "Multi-tenant: use setup → Provision ledger (the global /setup wizard is disabled). Preview walks the UI without writes."
                    : "Full path: welcome, Sheets, statements, rules. Preview walks the UI without changing your live connection or ledger."}
                </p>
              </>
            ) : (
              <EmptyState title="No sheet status" description="Is the API running?" />
            )}

            <div className="space-y-2 border-t border-white/10 pt-4 text-sm">
              <h3 className="text-sm font-semibold">API health</h3>
              {health ? (
                <ul className="text-pretty break-words text-ink-muted">
                  <li>Status: {health.status}</li>
                  <li>App: {health.app}</li>
                  <li>Auth: {health.auth_mode}</li>
                  <li>Spreadsheet configured: {health.spreadsheet_configured ? "yes" : "no"}</li>
                </ul>
              ) : (
                <Spinner />
              )}
            </div>
          </SettingsSection>

          {user?.role === "platform_admin" && user.multi_tenant ? (
            <>
              <AdminLegacySheetSection
                tenantReady={Boolean(user.tenant_ready || user.spreadsheet_bound)}
                onBound={() => void refresh()}
              />
              <AdminInvitesSection />
            </>
          ) : null}

          <SettingsSection id="ai" title="AI">
            <p className="text-pretty break-words text-xs text-ink-muted">
              Categorize + unknown cash CSV mapping. Platform uses a server xAI key;
              the writable sandbox demo also works offline with a local heuristic when
              no key is set. Nothing is applied until you confirm.
            </p>
            {aiStatusError && (
              <p className="text-pretty break-words text-xs text-danger">{aiStatusError}</p>
            )}
            {aiStatus && (
              <dl className="grid grid-cols-2 gap-2 text-xs">
                <div className="min-w-0">
                  <dt className="text-ink-faint">Mode</dt>
                  <dd className="break-words font-medium text-ink">{aiStatus.mode}</dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-ink-faint">Configured</dt>
                  <dd className="font-medium text-ink">
                    {aiStatus.configured ? "Yes" : "No"}
                  </dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-ink-faint">Model</dt>
                  <dd className="break-words font-medium text-ink">{aiStatus.model || "—"}</dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-ink-faint">Daily quota</dt>
                  <dd className="font-medium tabular-nums text-ink">
                    {aiStatus.quota_used}/{aiStatus.quota_cap} tokens
                  </dd>
                </div>
              </dl>
            )}
            {aiStatus?.sandbox_fallback && (
              <p className="rounded-lg border border-brand/25 bg-brand/10 px-2.5 py-1.5 text-pretty break-words text-[11px] text-ink-muted">
                Sandbox demo AI is active (local heuristics, no Grok API key). Real Grok
                needs <code className="text-ink-muted">AI_ENABLED=true</code> and{" "}
                <code className="text-ink-muted">XAI_API_KEY</code>.
              </p>
            )}
            {!aiStatus?.configured && !aiStatusError && (
              <p className="text-pretty break-words text-[11px] text-ink-faint">
                To enable real Grok: set <code className="text-ink-muted">AI_ENABLED=true</code>{" "}
                and <code className="text-ink-muted">XAI_API_KEY</code> in the API{" "}
                <code className="text-ink-muted">.env</code>, then restart. Sandbox demos
                still get Map/Suggest via fallback when{" "}
                <code className="text-ink-muted">AI_SANDBOX_FALLBACK</code> is on (default).
              </p>
            )}
          </SettingsSection>

          <SettingsSection id="export" title="Export">
            <p className="text-pretty break-words text-xs text-ink-muted">
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
          </SettingsSection>

          <SettingsSection id="jobs" title="Jobs">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
              <p className="min-w-0 text-pretty break-words text-xs text-ink-muted">
                Background FX maintenance (CNB rates + amount_usd / amount_czk). Safe to re-run;
                one job of each kind at a time.
              </p>
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
            {jobMsg && <p className="text-pretty break-words text-xs text-ok">{jobMsg}</p>}
            {jobError && (
              <p className="text-pretty break-words text-xs text-danger">{jobError}</p>
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
                            <span className="ml-1 text-pretty break-words text-danger">
                              · {j.error}
                            </span>
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
          </SettingsSection>

          <SettingsSection id="danger" title="Danger" danger>
            {!isReadOnly && (
              <div className="space-y-4">
                <div className="flex min-w-0 items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-sm font-semibold text-danger">Data cleanup</h3>
                    <p className="mt-1 text-pretty break-words text-xs text-ink-muted">
                      Permanently deletes rows for the selected areas only.{" "}
                      <strong className="text-ink">Categories &amp; rules</strong> removes category
                      trees and rules and unassigns categories on cash txs — it does{" "}
                      <strong className="text-ink">not</strong> delete uploaded statement history.
                      Use “All money history” or the cash/investments scopes to remove imports. Type{" "}
                      <span className="font-mono text-danger">DELETE</span> to confirm.
                    </p>
                  </div>
                  <button
                    type="button"
                    className="btn-ghost shrink-0 text-xs"
                    onClick={() => void refreshCleanupPreview()}
                    disabled={cleanupBusy}
                  >
                    Refresh counts
                  </button>
                </div>

                {cleanupError && (
                  <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-pretty break-words text-sm text-danger">
                    {cleanupError}
                  </div>
                )}

                {cleanupResult && (
                  <div className="rounded-xl border border-ok/30 bg-ok/10 px-3 py-2 text-pretty break-words text-sm text-ok">
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
                  <p className="text-pretty break-words text-xs text-ink-faint">
                    Cleanup API not available (restart the API if you just updated).
                  </p>
                ) : (
                  <>
                    <ul className="space-y-2">
                      {cleanup.scopes.map((s) => (
                        <li
                          key={s.id}
                          className="flex min-w-0 items-start gap-3 rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2"
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
                              <span className="text-pretty break-words text-sm font-medium">
                                {s.label}
                              </span>
                              <span className="font-mono text-xs text-ink-faint">
                                {s.total_rows} rows
                              </span>
                            </div>
                            <p className="text-pretty break-words text-xs text-ink-muted">
                              {s.description}
                            </p>
                            {s.notes ? (
                              <p className="mt-0.5 text-pretty break-words text-xs text-warn">
                                {s.notes}
                              </p>
                            ) : null}
                            <p className="mt-0.5 break-words font-mono text-[10px] text-ink-faint">
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
              </div>
            )}

            {showLabWipe && (
              <div className="space-y-3 rounded-xl border border-amber-400/30 p-4">
                <h3 className="text-sm font-semibold">Wipe lab ledger</h3>
                <p className="text-pretty break-words text-xs text-ink-muted">
                  Empties the disk ledger on <strong>this host</strong> (Railway volume or local
                  AppData). Does not touch Google Sheets or other accounts. Type{" "}
                  <code className="text-ink">WIPE LAB</code> to confirm.
                </p>
                {sheets?.path && (
                  <p className="break-all text-xs text-ink-faint">Ledger: {sheets.path}</p>
                )}
                {labWipeError && (
                  <p className="text-pretty break-words text-sm text-danger">{labWipeError}</p>
                )}
                {labWipeMsg && (
                  <p className="text-pretty break-words text-sm text-emerald-300">{labWipeMsg}</p>
                )}
                <input
                  className="input"
                  value={labWipeConfirm}
                  onChange={(e) => setLabWipeConfirm(e.target.value)}
                  placeholder="WIPE LAB"
                  autoComplete="off"
                  disabled={labWipeBusy || isReadOnly}
                />
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={labWipeBusy || isReadOnly || labWipeConfirm.trim() !== "WIPE LAB"}
                  onClick={() => {
                    void (async () => {
                      setLabWipeBusy(true);
                      setLabWipeError(null);
                      setLabWipeMsg(null);
                      try {
                        const out = await api.resetLabLedger({ confirm: "WIPE LAB" });
                        // Desk persist keys stay — comparison must survive wipe.
                        resetEmptyLabClientState();
                        const txs = Number(out.after?.Transactions ?? -1);
                        setLabWipeMsg(
                          txs === 0
                            ? "Lab ledger wiped. Opening new-user setup…"
                            : "Wipe finished with unexpected leftovers.",
                        );
                        navigate("/onboarding", { replace: true });
                      } catch (e) {
                        setLabWipeError(e instanceof Error ? e.message : "Wipe failed");
                      } finally {
                        setLabWipeBusy(false);
                      }
                    })();
                  }}
                >
                  {labWipeBusy ? "Wiping…" : "Wipe lab on this host"}
                </button>
              </div>
            )}
          </SettingsSection>
        </div>
      )}
    </LabNextChrome>
  );
}
