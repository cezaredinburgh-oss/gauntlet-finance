import type { ReactNode } from "react";

export function CoverageLine({
  pct,
  categorized,
  uncategorized,
  itemsLength,
  total,
  ladderText,
  children,
}: {
  pct: number;
  categorized: number;
  uncategorized: number;
  itemsLength: number;
  total: number;
  ladderText?: string | null;
  children?: ReactNode;
}) {
  const honesty =
    total > itemsLength
      ? `newest ${itemsLength.toLocaleString()} of ${total.toLocaleString()}`
      : `newest ${itemsLength.toLocaleString()}`;

  return (
    <div className="flex min-w-0 max-w-full flex-wrap items-center justify-between gap-2">
      <p className="min-w-0 max-w-full break-words text-sm text-ink-muted">
        <span className="font-medium text-ink">Ledger coverage (180d)</span>
        {" · "}
        {pct.toFixed(0)}%
        {" · "}
        {categorized.toLocaleString()} categorized
        {" · "}
        {uncategorized.toLocaleString()} uncategorized
        {" · "}
        {honesty}
        {ladderText ? (
          <span className="text-ink-faint"> · {ladderText}</span>
        ) : null}
      </p>
      {children}
    </div>
  );
}
