import { useMemo } from "react";
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
import type { TaxYearsSummary } from "../../../api/types";
import { d, formatCzk } from "../../../lib/money";

export function TaxGainsChart({
  byYear,
  exemptionDays = 1095,
}: {
  byYear: TaxYearsSummary;
  exemptionDays?: number;
}) {
  const chartData = useMemo(() => {
    if (!byYear.years?.length) return [];
    return byYear.years.map((row) => ({
      year: String(row.year),
      taxable: d(row.taxable_realized_gain_czk),
      exempt: d(row.exempt_realized_gain_czk),
    }));
  }, [byYear]);

  if (chartData.length === 0) return null;

  return (
    <div className="card p-5">
      <h2 className="mb-1 text-sm font-semibold">Realised gains by year</h2>
      <p className="mb-4 text-xs text-ink-faint">
        FIFO · {exemptionDays} days · CZK when stored · USD wealth context · not a filing
      </p>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="rgba(148,163,184,0.12)"
              vertical={false}
            />
            <XAxis dataKey="year" tick={{ fill: "#64748b", fontSize: 11 }} tickLine={false} />
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
              cursor={false}
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
            <Legend formatter={(v) => (v === "taxable" ? "Taxable CZK" : "Exempt CZK")} />
            <Bar
              dataKey="taxable"
              stackId="g"
              fill="#fbbf24"
              radius={[0, 0, 0, 0]}
              activeBar={false}
            />
            <Bar
              dataKey="exempt"
              stackId="g"
              fill="#34d399"
              radius={[4, 4, 0, 0]}
              activeBar={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
