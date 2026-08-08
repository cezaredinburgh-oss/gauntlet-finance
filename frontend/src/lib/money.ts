/** Money display helpers — native on rows; USD for totals. */

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

const czkFmt = new Intl.NumberFormat("cs-CZ", {
  style: "currency",
  currency: "CZK",
  maximumFractionDigits: 0,
});

const numFmt = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
});

const qtyFmt = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 6,
});

export function d(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
}

export function formatUsd(value: string | number | null | undefined): string {
  return usdFmt.format(d(value));
}

export function formatCzk(value: string | number | null | undefined): string {
  return czkFmt.format(d(value));
}

export function formatAmount(
  value: string | number | null | undefined,
  currency = "USD",
): string {
  const n = d(value);
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency.length === 3 ? currency : "USD",
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    return `${numFmt.format(n)} ${currency}`;
  }
}

export function formatQty(value: string | number | null | undefined): string {
  return qtyFmt.format(d(value));
}

/** True when a converted leg is present for display (no invented rates). */
export function hasMoneyValue(value: string | number | null | undefined): boolean {
  if (value === null || value === undefined || value === "") return false;
  return Number.isFinite(typeof value === "number" ? value : Number(value));
}
