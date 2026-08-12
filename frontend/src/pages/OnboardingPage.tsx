import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Cloud,
  ExternalLink,
  FileUp,
  LayoutDashboard,
  Shield,
  Sparkles,
  Tags,
  Wallet,
} from "lucide-react";
import { api, setupWizardUrl } from "../api/client";
import type {
  ApplyRulesResult,
  BootstrapRulesResult,
  CategoryCoverage,
  Health,
  SheetsStatus,
  UploadResult,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Spinner } from "../components/Spinner";
import { cn } from "../lib/cn";
import {
  ONBOARDING_STEPS,
  isStepId,
  markOnboardingComplete,
  markOnboardingStep,
  onboardingPath,
  type OnboardingStepId,
} from "../lib/onboarding";

const MAX_BATCH = 10;
const ACCEPT =
  ".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

type FileOutcome = {
  fileName: string;
  result?: UploadResult;
  error?: string;
};

function isStatementFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return name.endsWith(".csv") || name.endsWith(".xlsx");
}

const USPS = [
  {
    icon: Shield,
    title: "Your statements. Your sheet.",
    body: "Ledger lives in your private Google Spreadsheet — not a black-box desk import.",
  },
  {
    icon: LayoutDashboard,
    title: "Executive snapshot",
    body: "Home shows wealth, cash pulse, and alerts first — not a raw spreadsheet dump.",
  },
  {
    icon: Wallet,
    title: "Honest multi-currency",
    body: "USD primary, CZK on hover. Market rates only — we never invent FX.",
  },
  {
    icon: Sparkles,
    title: "Czech tax runway",
    body: "FIFO lots with 3-year (1095-day) exemption tracking on open positions.",
  },
  {
    icon: FileUp,
    title: "Banks you actually use",
    body: "Raiffeisen, Revolut cash/stocks/crypto, eToro — drop exports, we detect the format.",
  },
  {
    icon: Tags,
    title: "Spend truth",
    body: "Internal transfers and crypto-pot moves stay out of income/expense totals.",
  },
] as const;

export function OnboardingPage() {
  const navigate = useNavigate();
  const { user, refresh: refreshAuth } = useAuth();
  const [params, setParams] = useSearchParams();
  const preview = params.get("preview") === "1" || params.get("preview") === "true";
  const stepParam = params.get("step");
  const step: OnboardingStepId = isStepId(stepParam) ? stepParam : "welcome";
  const multiTenant = Boolean(user?.multi_tenant);

  const [health, setHealth] = useState<Health | null>(null);
  const [sheets, setSheets] = useState<SheetsStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [statusBusy, setStatusBusy] = useState(false);
  const [provisionMsg, setProvisionMsg] = useState<string | null>(null);
  const [provisionBusy, setProvisionBusy] = useState(false);

  const setStep = useCallback(
    (next: OnboardingStepId) => {
      if (!preview) markOnboardingStep(next);
      const p = new URLSearchParams(params);
      if (next === "welcome") p.delete("step");
      else p.set("step", next);
      if (preview) p.set("preview", "1");
      setParams(p, { replace: true });
    },
    [params, preview, setParams],
  );

  const refreshStatus = useCallback(async () => {
    setStatusBusy(true);
    setStatusError(null);
    try {
      const [h, s] = await Promise.all([
        api.health(),
        api.sheetsStatus().catch(() => null),
      ]);
      setHealth(h);
      setSheets(s);
      await refreshAuth();
    } catch (e) {
      setStatusError(e instanceof Error ? e.message : "Could not load status");
    } finally {
      setStatusBusy(false);
    }
  }, [refreshAuth]);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  const sheetConfigured = multiTenant
    ? Boolean(user?.tenant_ready || user?.spreadsheet_bound || sheets?.spreadsheet_id)
    : health?.spreadsheet_configured === true;
  const sheetsOk = multiTenant
    ? sheetConfigured || sheets?.ok === true || sheets?.backend === "memory"
    : sheets?.ok === true;

  async function runProvision() {
    if (preview) {
      setProvisionMsg("Preview: provision blocked — your live ledger was not changed.");
      return;
    }
    setProvisionBusy(true);
    setProvisionMsg(null);
    setStatusError(null);
    try {
      const r = await api.tenantProvision();
      setProvisionMsg(
        r.status === "already_provisioned"
          ? `Already provisioned (${r.spreadsheet_id ?? "sheet bound"}).`
          : `Provisioned (${r.backend ?? "ok"}): ${r.spreadsheet_id ?? ""}`,
      );
      await refreshAuth();
      await refreshStatus();
    } catch (e) {
      setStatusError(e instanceof Error ? e.message : "Provision failed");
    } finally {
      setProvisionBusy(false);
    }
  }
  const stepIdx = ONBOARDING_STEPS.findIndex((s) => s.id === step);

  function goNext() {
    const next = ONBOARDING_STEPS[Math.min(stepIdx + 1, ONBOARDING_STEPS.length - 1)];
    if (next) setStep(next.id);
  }

  function goBack() {
    const prev = ONBOARDING_STEPS[Math.max(stepIdx - 1, 0)];
    if (prev) setStep(prev.id);
  }

  function finish() {
    if (!preview) markOnboardingComplete();
    navigate("/", { replace: true });
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5 pb-10">
      {preview && (
        <div className="rounded-2xl border border-amber-400/40 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
          <strong className="font-semibold">Preview mode</strong>
          <span className="text-amber-100/85">
            {" "}
            — your live Google Sheet connection and ledger are not modified. Mutating actions
            are blocked.
          </span>
          <Link
            to={onboardingPath({ step })}
            className="mt-2 block text-xs font-medium text-brand underline-offset-2 hover:underline"
          >
            Exit preview (real setup)
          </Link>
        </div>
      )}

      <header className="space-y-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-brand">
          New user setup
        </p>
        <h1 className="text-2xl font-bold tracking-tight">Get Gauntlet ready</h1>
        <p className="text-sm text-ink-muted">
          Guided path: welcome → Google Sheets → bank statements → spending rules. About
          10–15 minutes.
        </p>
      </header>

      <nav className="flex flex-wrap gap-2" aria-label="Setup steps">
        {ONBOARDING_STEPS.map((s, i) => {
          const active = s.id === step;
          const done = i < stepIdx;
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => setStep(s.id)}
              className={cn(
                "rounded-full px-3 py-1.5 text-xs font-semibold transition",
                active && "bg-brand text-slate-950",
                !active && done && "bg-ok/15 text-ok border border-ok/30",
                !active && !done && "bg-white/5 text-ink-muted border border-white/10",
              )}
            >
              {done ? "✓ " : `${i + 1}. `}
              {s.short}
            </button>
          );
        })}
      </nav>

      {step === "welcome" && (
        <WelcomeStep onContinue={goNext} preview={preview} />
      )}
      {step === "sheets" && (
        <SheetsStep
          preview={preview}
          multiTenant={multiTenant}
          health={health}
          sheets={sheets}
          statusError={statusError}
          statusBusy={statusBusy}
          provisionBusy={provisionBusy}
          provisionMsg={provisionMsg}
          onProvision={() => void runProvision()}
          onRefresh={() => void refreshStatus()}
          onBack={goBack}
          onContinue={goNext}
          sheetConfigured={sheetConfigured}
          sheetsOk={sheetsOk}
        />
      )}
      {step === "upload" && (
        <UploadStep
          preview={preview}
          sheetConfigured={sheetConfigured}
          onBack={goBack}
          onContinue={goNext}
        />
      )}
      {step === "rules" && (
        <RulesStep
          preview={preview}
          sheetConfigured={sheetConfigured}
          onBack={goBack}
          onContinue={goNext}
        />
      )}
      {step === "ready" && (
        <ReadyStep
          preview={preview}
          sheetConfigured={sheetConfigured}
          sheetsOk={sheetsOk}
          onBack={goBack}
          onFinish={finish}
        />
      )}
    </div>
  );
}

function WelcomeStep({
  onContinue,
  preview,
}: {
  onContinue: () => void;
  preview: boolean;
}) {
  return (
    <div className="space-y-5">
      <section className="card space-y-3 p-5">
        <h2 className="text-lg font-semibold">Welcome to Gauntlet Finance</h2>
        <p className="text-sm text-ink-muted">
          Personal multi-currency finance desk: statements-only ledger, your Google Sheet as
          storage, executive Home, and Czech tax runway on investments.
        </p>
        <ol className="list-decimal space-y-1.5 pl-5 text-sm text-ink-muted">
          <li>Connect a private Google Spreadsheet (service account — guided).</li>
          <li>Upload bank/broker exports (CSV or eToro Excel).</li>
          <li>Bootstrap spending rules and triage uncategorized merchants.</li>
          <li>Use Home as your executive snapshot; dig into Spending &amp; Investments.</li>
        </ol>
      </section>

      <div className="grid gap-3 sm:grid-cols-2">
        {USPS.map((u) => (
          <div key={u.title} className="card flex gap-3 p-4">
            <div className="rounded-xl bg-brand/15 p-2 text-brand">
              <u.icon className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-semibold">{u.title}</div>
              <p className="mt-1 text-xs text-ink-muted">{u.body}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap justify-end gap-2">
        <Link to="/" className="btn-ghost">
          Skip for now
        </Link>
        <button type="button" className="btn-primary" onClick={onContinue}>
          {preview ? "Continue preview" : "Start setup"}
          <ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function SheetsStep({
  preview,
  multiTenant,
  health,
  sheets,
  statusError,
  statusBusy,
  provisionBusy,
  provisionMsg,
  onProvision,
  onRefresh,
  onBack,
  onContinue,
  sheetConfigured,
  sheetsOk,
}: {
  preview: boolean;
  multiTenant: boolean;
  health: Health | null;
  sheets: SheetsStatus | null;
  statusError: string | null;
  statusBusy: boolean;
  provisionBusy: boolean;
  provisionMsg: string | null;
  onProvision: () => void;
  onRefresh: () => void;
  onBack: () => void;
  onContinue: () => void;
  sheetConfigured: boolean;
  sheetsOk: boolean;
}) {
  const checks = useMemo(
    () => [
      {
        label: multiTenant ? "Tenant ledger bound" : "Spreadsheet ID configured",
        ok: sheetConfigured,
        detail: sheetConfigured
          ? multiTenant
            ? sheets?.spreadsheet_id
              ? `Bound: ${sheets.spreadsheet_id}`
              : "Bound for this account"
            : "Linked in app config"
          : multiTenant
            ? "Not provisioned yet"
            : "Not set yet",
      },
      {
        label: "Sheets connection",
        ok: sheetsOk,
        detail: sheets?.message || (sheetsOk ? "OK" : "Not connected or status unavailable"),
      },
      {
        label: "Backend",
        ok:
          sheets?.backend === "google" ||
          sheets?.backend === "google_sheets" ||
          sheets?.backend === "memory",
        detail: sheets?.backend ? String(sheets.backend) : health?.auth_mode || "—",
      },
    ],
    [sheetConfigured, sheetsOk, sheets, health, multiTenant],
  );

  return (
    <div className="space-y-5">
      <section className="card space-y-3 p-5">
        <div className="flex items-center gap-2 text-brand">
          <Cloud className="h-5 w-5" />
          <h2 className="text-lg font-semibold text-ink">
            {multiTenant ? "Your private ledger" : "Connect Google Sheets"}
          </h2>
        </div>
        <p className="text-sm text-ink-muted">
          {multiTenant ? (
            <>
              Multi-tenant mode creates a private spreadsheet (or memory ledger) for{" "}
              <strong className="text-ink">your account only</strong>. Use{" "}
              <strong className="text-ink">Provision ledger</strong> — the global{" "}
              <code className="text-xs text-brand">/setup</code> wizard is disabled here.
            </>
          ) : (
            <>
              Gauntlet stores your ledger in <strong className="text-ink">your</strong>{" "}
              spreadsheet via a service account. The full illustrated wizard lives on the API
              at <code className="text-xs text-brand">/setup</code>.
            </>
          )}
        </p>
        {preview && (
          <p className="rounded-xl border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
            Preview: provision and mutating wizard actions are blocked so your live connection
            stays intact.
          </p>
        )}
      </section>

      <section className="card space-y-3 p-5">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Connection status</h3>
          <button
            type="button"
            className="btn-secondary text-xs"
            disabled={statusBusy}
            onClick={onRefresh}
          >
            {statusBusy ? <Spinner className="h-3.5 w-3.5" /> : null}
            Recheck
          </button>
        </div>
        {statusError && (
          <p className="text-sm text-rose-300">{statusError}</p>
        )}
        <ul className="space-y-2">
          {checks.map((c) => (
            <li
              key={c.label}
              className="flex items-start gap-2 rounded-xl border border-white/10 bg-slate-950/40 px-3 py-2 text-sm"
            >
              <CheckCircle2
                className={cn("mt-0.5 h-4 w-4 shrink-0", c.ok ? "text-ok" : "text-ink-faint")}
              />
              <div>
                <div className="font-medium">{c.label}</div>
                <div className="text-xs text-ink-muted">{c.detail}</div>
              </div>
            </li>
          ))}
        </ul>
        {sheets?.service_account_email && (
          <p className="text-xs text-ink-faint">
            Service account: {sheets.service_account_email}
          </p>
        )}
      </section>

      {provisionMsg && <p className="text-sm text-ok">{provisionMsg}</p>}

      <div className="flex flex-wrap gap-2">
        {multiTenant ? (
          <button
            type="button"
            className="btn-primary inline-flex"
            disabled={provisionBusy || statusBusy}
            onClick={onProvision}
          >
            {provisionBusy ? <Spinner /> : null}
            Provision ledger
          </button>
        ) : (
          <a
            className="btn-primary inline-flex"
            href={setupWizardUrl()}
            target="_blank"
            rel="noreferrer"
          >
            {preview ? "Open Sheets wizard (browse carefully)" : "Open Sheets wizard"}
            <ExternalLink className="h-4 w-4" />
          </a>
        )}
        <button type="button" className="btn-secondary" onClick={onRefresh}>
          {multiTenant ? "Recheck status" : "I’ve finished — recheck"}
        </button>
      </div>

      <NavRow
        onBack={onBack}
        onContinue={onContinue}
        continueLabel={
          sheetConfigured || preview
            ? "Continue"
            : "Continue without sheet (not recommended)"
        }
        continueVariant={sheetConfigured || preview ? "primary" : "secondary"}
      />
    </div>
  );
}

function UploadStep({
  preview,
  sheetConfigured,
  onBack,
  onContinue,
}: {
  preview: boolean;
  sheetConfigured: boolean;
  onBack: () => void;
  onContinue: () => void;
}) {
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcomes, setOutcomes] = useState<FileOutcome[]>([]);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [previewBlocked, setPreviewBlocked] = useState(false);
  const inFlight = useRef(false);

  const uploadMany = useCallback(
    async (rawFiles: File[]) => {
      if (!rawFiles.length || inFlight.current) return;
      if (preview) {
        setPreviewBlocked(true);
        setBatchError(null);
        setOutcomes(
          rawFiles.slice(0, 3).map((f) => ({
            fileName: f.name,
            error: "Preview only — upload blocked (your ledger was not changed).",
          })),
        );
        return;
      }
      if (rawFiles.length > MAX_BATCH) {
        setBatchError(`Select at most ${MAX_BATCH} files at a time.`);
        return;
      }
      const files = rawFiles.filter(isStatementFile);
      if (!files.length) {
        setBatchError("Only .csv or .xlsx statement files are accepted.");
        return;
      }
      inFlight.current = true;
      setBusy(true);
      setBatchError(null);
      setPreviewBlocked(false);
      const next: FileOutcome[] = [];
      try {
        for (const file of files) {
          try {
            const result = await api.upload(file);
            next.push({ fileName: file.name, result });
          } catch (e) {
            next.push({
              fileName: file.name,
              error: e instanceof Error ? e.message : "Upload failed",
            });
          }
          setOutcomes([...next]);
        }
      } finally {
        inFlight.current = false;
        setBusy(false);
      }
    },
    [preview],
  );

  return (
    <div className="space-y-5">
      <section className="card space-y-3 p-5">
        <div className="flex items-center gap-2 text-brand">
          <FileUp className="h-5 w-5" />
          <h2 className="text-lg font-semibold text-ink">Upload bank statements</h2>
        </div>
        <p className="text-sm text-ink-muted">
          Export from your bank or broker and drop the files here. Supported: Raiffeisen CZ,
          Revolut (cash / stocks / crypto), eToro account statement (.xlsx). Institution is
          detected automatically. Same file re-upload is idempotent (SHA-256).
        </p>
        {!sheetConfigured && !preview && (
          <p className="rounded-xl border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
            Spreadsheet is not configured yet. Imports may not persist until Sheets is linked.
            Prefer finishing the Sheets step first.
          </p>
        )}
        {preview && (
          <p className="rounded-xl border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
            Preview: dropzone is interactive but <strong>will not upload</strong> to your
            ledger.
          </p>
        )}
      </section>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          const list = e.dataTransfer.files;
          if (list?.length) void uploadMany(Array.from(list));
        }}
        className={cn(
          "card flex flex-col items-center justify-center gap-3 border-2 border-dashed px-6 py-14 text-center transition",
          drag ? "border-brand bg-brand/5" : "border-white/10",
          busy && "pointer-events-none opacity-70",
        )}
      >
        <div className="rounded-2xl bg-brand/15 p-4 text-brand">
          <FileUp className="h-8 w-8" />
        </div>
        <p className="font-semibold">Drag & drop statements</p>
        <p className="text-sm text-ink-muted">CSV or eToro .xlsx · up to {MAX_BATCH} files</p>
        <label className="btn-primary cursor-pointer">
          {busy ? <Spinner className="border-t-slate-900" /> : null}
          Browse files
          <input
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            disabled={busy}
            onChange={(e) => {
              const list = e.target.files;
              if (list?.length) void uploadMany(Array.from(list));
              e.target.value = "";
            }}
          />
        </label>
      </div>

      {batchError && <p className="text-sm text-rose-300">{batchError}</p>}
      {previewBlocked && (
        <p className="text-sm text-amber-200">Upload blocked in preview — ledger unchanged.</p>
      )}

      {outcomes.length > 0 && (
        <ul className="space-y-2">
          {outcomes.map((o) => (
            <li
              key={o.fileName + (o.result?.content_sha256 || o.error || "")}
              className="card flex items-start gap-2 px-4 py-3 text-sm"
            >
              {o.error ? (
                <span className="text-rose-300">✗</span>
              ) : (
                <CheckCircle2 className="h-4 w-4 shrink-0 text-ok" />
              )}
              <div>
                <div className="font-medium">{o.fileName}</div>
                {o.error ? (
                  <div className="text-xs text-rose-300/90">{o.error}</div>
                ) : o.result ? (
                  <div className="text-xs text-ink-muted">
                    {o.result.status}
                    {o.result.institution ? ` · ${o.result.institution}` : ""}
                    {o.result.message ? ` — ${o.result.message}` : ""}
                  </div>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}

      <p className="text-xs text-ink-faint">
        Full history and retry live on the{" "}
        <Link to="/upload" className="text-brand hover:underline">
          Upload
        </Link>{" "}
        page after setup.
      </p>

      <NavRow onBack={onBack} onContinue={onContinue} continueLabel="Continue to rules" />
    </div>
  );
}

function RulesStep({
  preview,
  sheetConfigured,
  onBack,
  onContinue,
}: {
  preview: boolean;
  sheetConfigured: boolean;
  onBack: () => void;
  onContinue: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<CategoryCoverage | null>(null);
  const [bootstrap, setBootstrap] = useState<BootstrapRulesResult | null>(null);
  const [apply, setApply] = useState<ApplyRulesResult | null>(null);

  const loadCoverage = useCallback(async () => {
    try {
      const c = await api.categoryCoverage(180);
      setCoverage(c);
    } catch {
      /* optional if empty ledger */
    }
  }, []);

  useEffect(() => {
    void loadCoverage();
  }, [loadCoverage]);

  async function runEnsure() {
    if (preview) {
      setMsg("Preview: ensure-defaults skipped — categories on your sheet unchanged.");
      return;
    }
    setBusy("ensure");
    setError(null);
    try {
      const r = await api.ensureCategories();
      setMsg(
        `Defaults ready: created ${r.created}, updated ${r.updated} (${r.total_defaults} total defaults).`,
      );
      await loadCoverage();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ensure defaults failed");
    } finally {
      setBusy(null);
    }
  }

  async function runBootstrap() {
    if (preview) {
      setMsg("Preview: bootstrap-rules skipped — no bulk rewrite of your ledger.");
      return;
    }
    setBusy("bootstrap");
    setError(null);
    try {
      const r = await api.bootstrapRules(true);
      setBootstrap(r);
      setMsg(
        `Bootstrap: ${r.rules_created} rules created, apply filled ${r.apply?.filled ?? 0}.`,
      );
      await loadCoverage();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Bootstrap failed");
    } finally {
      setBusy(null);
    }
  }

  async function runApply() {
    if (preview) {
      setMsg("Preview: apply-rules skipped.");
      return;
    }
    setBusy("apply");
    setError(null);
    try {
      const r = await api.applyRules();
      setApply(r);
      setMsg(`Applied rules: filled ${r.filled} of ${r.scanned} scanned.`);
      await loadCoverage();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Apply rules failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <section className="card space-y-3 p-5">
        <div className="flex items-center gap-2 text-brand">
          <Tags className="h-5 w-5" />
          <h2 className="text-lg font-semibold text-ink">Rules &amp; categorization</h2>
        </div>
        <p className="text-sm text-ink-muted">
          Seed default categories, install starter keyword rules, then scan blanks. Finish fine
          work in the full Categorize workspace (merchant rules, bulk assign).
        </p>
        <ul className="list-disc space-y-1 pl-5 text-xs text-ink-muted">
          <li>Internal transfers are flagged on import and stay out of spend totals.</li>
          <li>Stable category IDs — we do not renumber categories by name.</li>
          <li>Rules fill blanks only; manual overrides are preserved.</li>
        </ul>
        {preview && (
          <p className="rounded-xl border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
            Preview: buttons show the flow but do not write categories or reclassify
            transactions.
          </p>
        )}
        {!sheetConfigured && !preview && (
          <p className="text-xs text-amber-200">
            Sheet not configured — category writes need a linked ledger.
          </p>
        )}
      </section>

      {coverage && (
        <section className="card space-y-2 p-5 text-sm">
          <h3 className="font-semibold">Coverage (180d expenses)</h3>
          <p className="text-ink-muted">
            {coverage.coverage_pct.toFixed(1)}% categorized · {coverage.rules_count} rules ·{" "}
            {coverage.categories_count} categories
          </p>
          {coverage.top_uncategorized_merchants?.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-faint">
                Top uncategorized
              </p>
              <ul className="space-y-1 text-xs text-ink-muted">
                {coverage.top_uncategorized_merchants.slice(0, 5).map((m) => (
                  <li key={m.label} className="flex justify-between gap-2">
                    <span className="truncate">{m.label}</span>
                    <span className="shrink-0 tabular-nums">${m.amount_usd}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-secondary"
          disabled={busy != null}
          onClick={() => void runEnsure()}
        >
          {busy === "ensure" ? <Spinner /> : null}
          1. Ensure default categories
        </button>
        <button
          type="button"
          className="btn-secondary"
          disabled={busy != null}
          onClick={() => void runBootstrap()}
        >
          {busy === "bootstrap" ? <Spinner /> : null}
          2. Bootstrap starter rules
        </button>
        <button
          type="button"
          className="btn-secondary"
          disabled={busy != null}
          onClick={() => void runApply()}
        >
          {busy === "apply" ? <Spinner /> : null}
          3. Apply rules to blanks
        </button>
        <Link to="/expenses/categorize" className="btn-primary inline-flex">
          Open full Categorize
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>

      {msg && <p className="text-sm text-ok">{msg}</p>}
      {error && <p className="text-sm text-rose-300">{error}</p>}
      {(bootstrap || apply) && !preview && (
        <p className="text-xs text-ink-faint">
          Results saved to your ledger. Refine anytime under Expenses → Categorize.
        </p>
      )}

      <NavRow onBack={onBack} onContinue={onContinue} continueLabel="Continue" />
    </div>
  );
}

function ReadyStep({
  preview,
  sheetConfigured,
  sheetsOk,
  onBack,
  onFinish,
}: {
  preview: boolean;
  sheetConfigured: boolean;
  sheetsOk: boolean;
  onBack: () => void;
  onFinish: () => void;
}) {
  return (
    <div className="space-y-5">
      <section className="card space-y-3 p-5">
        <div className="flex items-center gap-2 text-ok">
          <CheckCircle2 className="h-6 w-6" />
          <h2 className="text-lg font-semibold text-ink">
            {preview ? "Preview complete" : "You're ready"}
          </h2>
        </div>
        <p className="text-sm text-ink-muted">
          {preview
            ? "You walked the full new-user path without changing your live connection or data."
            : "Head to the executive Home for wealth and cash pulse. Upload more statements anytime; refine rules in Categorize."}
        </p>
        <ul className="space-y-2 text-sm">
          <li className="flex gap-2">
            <CheckCircle2
              className={cn("h-4 w-4 mt-0.5", sheetConfigured ? "text-ok" : "text-ink-faint")}
            />
            Spreadsheet configured: {sheetConfigured ? "yes" : "not yet"}
          </li>
          <li className="flex gap-2">
            <CheckCircle2
              className={cn("h-4 w-4 mt-0.5", sheetsOk ? "text-ok" : "text-ink-faint")}
            />
            Sheets reachable: {sheetsOk ? "yes" : "check Settings / wizard"}
          </li>
        </ul>
        <div className="rounded-xl border border-white/10 bg-slate-950/40 px-3 py-2 text-xs text-ink-muted">
          Tips: internal transfers are not spend · crypto pot funding stays internal · tax
          runway lives under Investments · never invent FX.
        </div>
      </section>

      <div className="flex flex-wrap justify-between gap-2">
        <button type="button" className="btn-ghost" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </button>
        <button type="button" className="btn-primary" onClick={onFinish}>
          {preview ? "Close preview → Home" : "Open executive Home"}
          <ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function NavRow({
  onBack,
  onContinue,
  continueLabel = "Continue",
  continueVariant = "primary",
}: {
  onBack: () => void;
  onContinue: () => void;
  continueLabel?: string;
  continueVariant?: "primary" | "secondary";
}) {
  return (
    <div className="flex flex-wrap justify-between gap-2 pt-1">
      <button type="button" className="btn-ghost" onClick={onBack}>
        <ArrowLeft className="h-4 w-4" />
        Back
      </button>
      <button
        type="button"
        className={continueVariant === "primary" ? "btn-primary" : "btn-secondary"}
        onClick={onContinue}
      >
        {continueLabel}
        <ArrowRight className="h-4 w-4" />
      </button>
    </div>
  );
}
