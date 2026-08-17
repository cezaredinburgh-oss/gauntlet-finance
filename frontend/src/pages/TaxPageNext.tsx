import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Download } from "lucide-react";
import { api, API_BASE } from "../api/client";
import type { TaxReport, TaxYearsSummary } from "../api/types";
import { PageLoader } from "../components/Spinner";
import { InvestmentsPageShell } from "../features/investments/InvestmentsPageShell";
import { TaxDisposalsTable } from "../features/investments/tax-next/TaxDisposalsTable";
import { TaxFilingKitLegend } from "../features/investments/tax-next/TaxFilingKitLegend";
import { TaxGainsChart } from "../features/investments/tax-next/TaxGainsChart";
import { TaxOpenLotsTable } from "../features/investments/tax-next/TaxOpenLotsTable";
import { TaxYearCard } from "../features/investments/tax-next/TaxYearCard";

export function TaxPageNext() {
  const [years, setYears] = useState<number[]>([]);
  const [year, setYear] = useState<number>(new Date().getFullYear());
  const [report, setReport] = useState<TaxReport | null>(null);
  const [byYear, setByYear] = useState<TaxYearsSummary | null>(null);
  const [tab, setTab] = useState<"taxable" | "exempt" | "open">("taxable");
  const [loading, setLoading] = useState(true);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [catalogTick, setCatalogTick] = useState(0);
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [y, summary] = await Promise.all([api.taxYears(), api.taxSummaryByYear()]);
        if (cancelled) return;
        const list = y.years?.length ? y.years : [y.default_year];
        setYears(list);
        setYear((prev) => (list.includes(prev) ? prev : y.default_year));
        setByYear(summary);
        setCatalogError(null);
      } catch (e) {
        if (!cancelled) setCatalogError(e instanceof Error ? e.message : "Failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [catalogTick]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setReportError(null);
      try {
        const r = await api.taxReport({ year });
        if (!cancelled) setReport(r);
      } catch (e) {
        if (!cancelled) {
          setReportError(e instanceof Error ? e.message : "Failed to load tax report");
          setReport(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [year, reloadTick]);

  const error = catalogError ?? reportError;

  function retryAll() {
    setCatalogTick((n) => n + 1);
    setReloadTick((n) => n + 1);
  }

  const rows =
    tab === "taxable"
      ? report?.taxable_disposals ?? []
      : tab === "exempt"
        ? report?.exempt_disposals ?? []
        : [];

  function downloadCsv(table: "taxable" | "exempt" | "all") {
    const url = `${API_BASE}/tax-report?year=${year}&format=csv&table=${table}`;
    window.open(url, "_blank", "noopener,noreferrer");
  }

  function downloadJson() {
    if (!report) return;
    const blob = new Blob([JSON.stringify(report, null, 2)], {
      type: "application/json",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `tax-report-${year}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function downloadYearEndPack() {
    window.open(api.yearEndExportUrl(year), "_blank", "noopener,noreferrer");
  }

  return (
    <InvestmentsPageShell
      active="tax"
      title="Tax report"
      subtitle="On-screen FIFO · not a filing · official use is the pack"
    >
      {error && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
          <span>{error}</span>
          <button type="button" className="btn-ghost text-xs text-ink" onClick={retryAll}>
            Retry
          </button>
        </div>
      )}

      <div className="card p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <label className="label">Tax year</label>
            <select
              className="input w-auto min-w-[8rem]"
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
            >
              {(years.length ? years : [year]).map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-secondary text-xs" onClick={downloadJson}>
              <Download className="h-3.5 w-3.5" />
              JSON
            </button>
            <button
              type="button"
              className="btn-secondary text-xs"
              onClick={() => downloadCsv("taxable")}
            >
              <Download className="h-3.5 w-3.5" />
              Taxable CSV
            </button>
            <button
              type="button"
              className="btn-secondary text-xs"
              onClick={() => downloadCsv("exempt")}
            >
              <Download className="h-3.5 w-3.5" />
              Exempt CSV
            </button>
            <button type="button" className="btn-primary text-xs" onClick={downloadYearEndPack}>
              <Download className="h-3.5 w-3.5" />
              Year-end pack
            </button>
          </div>
        </div>
        <TaxFilingKitLegend year={year} />
      </div>

      {loading && <PageLoader label="Loading tax report…" />}

      {!loading && report && (
        <>
          <TaxYearCard report={report} />
          {byYear ? (
            <TaxGainsChart byYear={byYear} exemptionDays={report.meta.exemption_days} />
          ) : null}

          <div className="card overflow-hidden">
            <div className="flex flex-wrap gap-1 border-b border-white/10 p-2">
              {(
                [
                  ["taxable", `Taxable (${report.summary.taxable_disposal_count})`],
                  ["exempt", `Exempt (${report.summary.exempt_disposal_count})`],
                  ["open", `Open lots (${report.open_positions.length})`],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className={
                    tab === id
                      ? "rounded-lg bg-brand/20 px-3 py-1.5 text-xs font-semibold text-brand"
                      : "rounded-lg px-3 py-1.5 text-xs font-semibold text-ink-muted hover:text-ink"
                  }
                  onClick={() => setTab(id)}
                >
                  {label}
                </button>
              ))}
            </div>

            {tab !== "open" ? (
              <TaxDisposalsTable
                key={tab}
                rows={rows}
                emptyTitle="No disposals"
                emptyDescription={`No ${tab} lot allocations in ${year}.`}
              />
            ) : (
              <TaxOpenLotsTable positions={report.open_positions} />
            )}
          </div>

          <p className="text-[11px] leading-relaxed text-ink-faint">
            {report.meta.notes} Exemption window: {report.meta.exemption_days} days · as of{" "}
            {report.meta.as_of}.{" "}
            <span>
              Open-lot runway lives on{" "}
              <Link to="/investments?focus=tax_runway" className="text-brand hover:underline">
                Holdings
              </Link>{" "}
              /{" "}
              <Link to="/" className="text-brand hover:underline">
                Home
              </Link>
              .
            </span>
          </p>
        </>
      )}
    </InvestmentsPageShell>
  );
}
