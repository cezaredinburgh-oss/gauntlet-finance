import type { AlertItem } from "../../api/types";

export type AlertDomain = "spending" | "crypto" | "stocks";

export type AlertBucketCounts = {
  spending: number;
  crypto: number;
  stocks: number;
  total: number;
};

/**
 * Bucket alerts for Home summary chips.
 * Spending = cash/categorize/FX; crypto vs stocks from DCA ticker + digest asset class
 * and investment hrefs (tax/prices default to stocks unless clearly crypto).
 */
export function summarizeAlertBuckets(
  alerts: AlertItem[],
  digests: Array<{ ticker: string; asset_class?: string | null }> = [],
): AlertBucketCounts {
  const acByTicker = new Map<string, string>();
  for (const d of digests) {
    acByTicker.set(d.ticker.toUpperCase(), (d.asset_class || "").toLowerCase());
  }

  let spending = 0;
  let crypto = 0;
  let stocks = 0;

  for (const a of alerts) {
    const domain = classifyAlert(a, acByTicker);
    if (domain === "spending") spending += 1;
    else if (domain === "crypto") crypto += 1;
    else stocks += 1;
  }

  return {
    spending,
    crypto,
    stocks,
    total: spending + crypto + stocks,
  };
}

function classifyAlert(
  a: AlertItem,
  acByTicker: Map<string, string>,
): AlertDomain {
  const domainHint = (a.domain || "").toLowerCase();
  if (domainHint === "crypto" || domainHint === "stocks" || domainHint === "spending") {
    return domainHint;
  }

  const href = (a.href || "").toLowerCase();
  const title = (a.title || "").toLowerCase();
  const body = (a.body || "").toLowerCase();
  const id = (a.id || "").toLowerCase();
  const blob = `${id} ${title} ${body} ${href}`;

  // DCA: id = dca_opportunity_TICKER
  const dcaMatch = /^dca_opportunity_(.+)$/i.exec(a.id || "");
  if (dcaMatch) {
    const t = dcaMatch[1].toUpperCase();
    const ac = acByTicker.get(t) || "";
    if (ac === "crypto") return "crypto";
    return "stocks";
  }

  if (
    href.includes("/expenses") ||
    href.includes("categorize") ||
    title.includes("spend") ||
    title.includes("uncategor") ||
    title.includes("transfer") ||
    title.includes("missing fx") ||
    title.includes("fixed cost") ||
    title.includes("outflow") ||
    title.includes("unusual ") ||
    blob.includes("spending")
  ) {
    return "spending";
  }

  if (
    blob.includes("crypto") ||
    blob.includes("bitcoin") ||
    blob.includes(" eth")
  ) {
    return "crypto";
  }

  // Tax runway, missing prices, DCA board, investments
  if (
    href.includes("/investments") ||
    title.includes("tax-free") ||
    title.includes("tax free") ||
    title.includes("market price") ||
    title.includes("dca")
  ) {
    return "stocks";
  }

  // Default: spending-side ops if unknown
  return "spending";
}
