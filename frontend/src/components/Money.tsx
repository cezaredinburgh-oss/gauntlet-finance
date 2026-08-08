import { formatAmount, formatCzk, formatUsd, d, hasMoneyValue } from "../lib/money";
import { cn } from "../lib/cn";

type Props = {
  /** Primary amount — statement-native for rows; USD for aggregate cards */
  amount: string | number | null | undefined;
  currency?: string;
  /** Historical CZK leg when known (never invent) */
  amountCzk?: string | number | null;
  /** Historical USD leg when known (never invent) */
  amountUsd?: string | number | null;
  /** inline = secondary under primary; hover = CZK/USD only in title; none = hide */
  secondaryMode?: "inline" | "hover" | "none";
  className?: string;
  size?: "sm" | "md" | "lg";
  align?: "left" | "right";
  signed?: boolean;
};

/**
 * Primary = amount + currency (native on transaction rows).
 * Secondary = stored historical conversion only:
 *   - USD-native → CZK when amountCzk present
 *   - any other → USD when amountUsd present
 * Missing converted legs: no secondary (never a hardcoded FX constant).
 */
export function Money({
  amount,
  currency = "USD",
  amountCzk,
  amountUsd,
  secondaryMode = "inline",
  className,
  size = "md",
  align = "left",
  signed = false,
}: Props) {
  const n = d(amount);
  const ccy = (currency || "USD").toUpperCase();
  const primary =
    ccy === "USD" ? formatUsd(n) : formatAmount(n, ccy);

  let secondary: string | null = null;
  if (ccy === "USD") {
    if (hasMoneyValue(amountCzk)) {
      secondary = formatCzk(amountCzk);
    }
  } else if (hasMoneyValue(amountUsd)) {
    secondary = formatUsd(amountUsd);
  } else if (ccy !== "CZK" && hasMoneyValue(amountCzk)) {
    // Non-USD/non-CZK without USD leg: show CZK only if stored
    secondary = formatCzk(amountCzk);
  }

  const color =
    signed && n !== 0
      ? n > 0
        ? "text-ok"
        : "text-danger"
      : "text-ink";

  const sizeCls =
    size === "lg"
      ? "text-2xl font-semibold tracking-tight"
      : size === "sm"
        ? "text-sm font-medium"
        : "text-base font-semibold";

  const showInline = secondaryMode === "inline" && secondary;
  const title = secondaryMode === "hover" && secondary ? secondary : undefined;

  return (
    <span
      className={cn(
        "inline-flex flex-col leading-tight",
        align === "right" && "items-end text-right",
        className,
      )}
      title={title}
    >
      <span className={cn(sizeCls, color)}>
        {signed && n > 0 ? "+" : ""}
        {primary}
      </span>
      {showInline && (
        <span className="text-[11px] font-normal text-ink-faint">{secondary}</span>
      )}
    </span>
  );
}
