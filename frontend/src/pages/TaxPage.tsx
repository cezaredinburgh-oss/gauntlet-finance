import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Download } from "lucide-react";
import { api, API_BASE } from "../api/client";
import type { TaxReport, TaxYearsSummary } from "../api/types";
import { EmptyState, PageLoader } from "../components/Spinner";
import { d, formatCzk, formatUsd } from "../lib/money";
import { InvestmentsSubNav } from "./InvestmentsPage";

export function TaxPage() {
  const [years, setYears] = useState<number[]>([]);
  const [year, setYear] = useState<number>(new Date().getFullYear());
  const [report, setReport] = useState<TaxReport | null>(null);
  const [byYear, setByYear] = useState<TaxYearsSummary | null>(null);
  const [tab, setTab] = useState<"taxable" | "exempt" | "open">("taxable");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [y, summary] = await Promise.all([
          api.taxYears(),
          api.taxSummaryByYear(),
        ]);
        if (cancelled) return;
        setYears(y.years?.length ? y.years : [y.default_year]);
        setYear(y.default_year);
        setByYear(summary);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const r = await api.taxReport({ year });
        if (!cancelled) setReport(r);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load tax report");
          setReport(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [year]);

  const chartData = useMemo(() => {
    if (!byYear?.years?.length) return [];
    return byYear.years.map((row) => ({
      year: String(row.year),
      taxable: d(row.taxable_realized_gain_czk),
      exempt: d(row.exempt_realized_gain_czk),
    }));
  }, [byYear]);

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
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Tax report</h1>
        <p className="text-sm text-ink-muted">
          Realised disposals from FIFO lot allocations · CZK primary reporting · not
          tax advice
        </p>
        <InvestmentsSubNav active="tax" />
      </div>

      {error && (
        <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      )}

      <div className="card flex flex-wrap items-end justify-between gap-3 p-4">
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
          <button
            type="button"
            className="btn-primary text-xs"
            onClick={downloadYearEndPack}
            title="ZIP: tax JSON/CSV, open lots, multi-year gains, category spend, statement files"
          >
            <Download className="h-3.5 w-3.5" />
            Year-end pack
          </button>
        </div>
      </div>

      {loading && <PageLoader label="Loading tax report…" />}

      {!loading && report && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi
              label="Taxable gain (CZK)"
              value={formatCzk(report.summary.taxable_realized_gain_czk)}
              tone="warn"
            />
            <Kpi
              label="Exempt gain (CZK)"
              value={formatCzk(report.summary.exempt_realized_gain_czk)}
              tone="ok"
            />
            <Kpi
              label="Total gain (USD)"
              value={formatUsd(report.summary.total_realized_gain_usd)}
            />
            <Kpi
              label="Disposals"
              value={`${report.summary.taxable_disposal_count} tax · ${report.summary.exempt_disposal_count} free`}
            />
          </div>

          {chartData.length > 0 && (
            <div className="card p-5">
              <h2 className="mb-1 text-sm font-semibold">Realised gains by year</h2>
              <p className="mb-4 text-xs text-ink-faint">
                CZK · taxable vs 3-year exempt (from lot allocations)
              </p>
              <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke="rgba(148,163,184,0.12)"
                      vertical={false}
                    />
                    <XAxis
                      dataKey="year"
                      tick={{ fill: "#64748b", fontSize: 11 }}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fill: "#64748b", fontSize: 11 }}
                      tickLine={false}
                      axisLine={false}
                      width={56}
                      tickFormatter={(v) =>
                        new Intl.NumberFormat("en-US", {
                          notation: "compact",
                          maximumFractionDigits: 1,
                        }).format(Number(v))
                      }
                    />
                    <Tooltip
                      contentStyle={{
                        background: "#0f172a",
                        border: "1px solid rgba(148,163,184,0.25)",
                        borderRadius: 12,
                        fontSize: 12,
                      }}
                      formatter={(value: number, name: string) => [
                        formatCzk(value),
                        name === "taxable" ? "Taxable" : "Exempt",
                      ]}
                    />
                    <Legend
                      formatter={(v) => (v === "taxable" ? "Taxable CZK" : "Exempt CZK")}
                    />
                    <Bar dataKey="taxable" stackId="g" fill="#fbbf24" radius={[0, 0, 0, 0]} />
                    <Bar dataKey="exempt" stackId="g" fill="#34d399" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

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

            {tab !== "open" && (
              <div className="overflow-x-auto">
                {rows.length === 0 ? (
                  <EmptyState
                    title="No disposals"
                    description={`No ${tab} lot allocations in ${year}.`}
                  />
                ) : (
                  <table className="w-full text-left text-sm">
                    <thead className="text-xs text-ink-faint">
                      <tr>
                        <th className="px-3 py-2 font-medium">Date</th>
                        <th className="px-3 py-2 font-medium">Ticker</th>
                        <th className="px-3 py-2 font-medium text-right">Qty</th>
                        <th className="px-3 py-2 font-medium text-right">Gain CZK</th>
                        <th className="px-3 py-2 font-medium text-right">Gain USD</th>
                        <th className="px-3 py-2 font-medium text-right">Days held</th>
                        <th className="px-3 py-2 font-medium">Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.id} className="border-t border-white/5">
                          <td className="px-3 py-2 tabular-nums text-ink-muted">{r.date}</td>
                          <td className="px-3 py-2 font-medium">{r.ticker || "—"}</td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {r.quantity ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {formatCzk(r.realized_gain_czk)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {formatUsd(r.realized_gain_usd)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-ink-muted">
                            {r.holding_period_days ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-ink-faint">{r.source || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            {tab === "open" && (
              <div className="overflow-x-auto">
                {report.open_positions.length === 0 ? (
                  <EmptyState title="No open lots" description="Import investment statements first." />
                ) : (
                  <table className="w-full text-left text-sm">
                    <thead className="text-xs text-ink-faint">
                      <tr>
                        <th className="px-3 py-2 font-medium">Ticker</th>
                        <th className="px-3 py-2 font-medium text-right">Qty</th>
                        <th className="px-3 py-2 font-medium text-right">Tax-free qty</th>
                        <th className="px-3 py-2 font-medium text-right">Pending qty</th>
                        <th className="px-3 py-2 font-medium text-right">Cost USD</th>
                        <th className="px-3 py-2 font-medium text-right">Cost CZK</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.open_positions.map((p) => (
                        <tr key={p.ticker} className="border-t border-white/5">
                          <td className="px-3 py-2 font-medium">{p.ticker}</td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {p.total_quantity}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-ok">
                            {p.quantity_tax_free}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-warn">
                            {p.quantity_pending}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {formatUsd(p.cost_basis_usd)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {formatCzk(p.cost_basis_czk)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>

          <p className="text-[11px] leading-relaxed text-ink-faint">
            {report.meta.notes} Exemption window: {report.meta.exemption_days} days · as of{" "}
            {report.meta.as_of}.
          </p>
        </>
      )}
    </div>
  );
}

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "ok" | "warn";
}) {
  return (
    <div className="card px-4 py-3">
      <div className="text-[10px] font-medium uppercase tracking-wide text-ink-faint">
        {label}
      </div>
      <div
        className={
          tone === "ok"
            ? "mt-1 text-lg font-semibold tabular-nums text-ok"
            : tone === "warn"
              ? "mt-1 text-lg font-semibold tabular-nums text-warn"
              : "mt-1 text-lg font-semibold tabular-nums"
        }
      >
        {value}
      </div>
    </div>
  );
}
