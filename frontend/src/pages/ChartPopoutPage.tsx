import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { TickerDigest } from "../api/types";
import {
  PositionHistoryChart,
  type ChartScope,
} from "../features/investments/PositionHistoryChart";
import { EmptyState, PageLoader } from "../components/Spinner";

function parseScope(params: URLSearchParams): ChartScope {
  const scope = params.get("scope") || "all";
  if (scope === "ticker") {
    const t = (params.get("ticker") || "").toUpperCase();
    if (t) return { kind: "ticker", ticker: t };
  }
  if (scope === "asset_class") {
    const ac = params.get("asset_class") || "";
    if (ac.toLowerCase() === "crypto") return { kind: "asset_class", asset_class: "Crypto" };
    if (ac.toLowerCase() === "stock") return { kind: "asset_class", asset_class: "Stock" };
  }
  return { kind: "all" };
}

/** Full-viewport chrome for side-by-side chart watching — sizes with the window. */
export function ChartPopoutPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [digests, setDigests] = useState<TickerDigest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const scope = useMemo(() => parseScope(searchParams), [searchParams]);

  useEffect(() => {
    document.title = "Gauntlet · Live chart";
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const dig = await api.tickerDigests();
        if (!cancelled) {
          setDigests(dig.tickers);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const onScopeChange = (next: ChartScope) => {
    const q = new URLSearchParams(searchParams);
    if (next.kind === "ticker") {
      q.set("scope", "ticker");
      q.set("ticker", next.ticker);
      q.delete("asset_class");
    } else if (next.kind === "asset_class") {
      q.set("scope", "asset_class");
      q.set("asset_class", next.asset_class);
      q.delete("ticker");
    } else {
      q.set("scope", "all");
      q.delete("ticker");
      q.delete("asset_class");
    }
    setSearchParams(q, { replace: true });
  };

  if (loading) {
    return (
      <div className="flex h-[100dvh] items-center justify-center bg-[#070b12]">
        <PageLoader label="Opening chart…" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex h-[100dvh] items-center justify-center bg-[#070b12] p-4">
        <EmptyState title="Couldn’t open chart" description={error} />
      </div>
    );
  }

  return (
    <div className="box-border flex h-[100dvh] max-h-[100dvh] min-h-0 flex-col overflow-hidden bg-[#070b12] p-1.5 sm:p-2">
      <div className="min-h-0 flex-1">
        <PositionHistoryChart
          digests={digests}
          scope={scope}
          onScopeChange={onScopeChange}
          variant="popout"
          showPopOut={false}
          preferIntraday
        />
      </div>
    </div>
  );
}
