import { formatAmount, formatCzk, formatUsd, d, estimateCzkFromUsd } from "../lib/money";
import { cn } from "../lib/cn";

type Props = {
  /** Primary amount */
  amount: string | number | null | undefined;
  currency?: string;
  /** Optional CZK amount when known */
  amountCzk?: string | number | null;
  /** If amount is USD and amountCzk missing, estimate for secondary line */
  estimateCzk?: boolean;
  /** inline = secondary under primary; hover = CZK only in title/tooltip; none = hide */
  secondaryMode?: "inline" | "hover" | "none";
  className?: string;
  size?: "sm" | "md" | "lg";
  align?: "left" | "right";
  signed?: boolean;
};

export function Money({
  amount,
  currency = "USD",
  amountCzk,
  estimateCzk = true,
  secondaryMode = "inline",
  className,
  size = "md",
  align = "left",
  signed = false,
}: Props) {
  const n = d(amount);
  const primary =
    currency === "USD"
      ? formatUsd(n)
      : formatAmount(n, currency);

  let secondary: string | null = null;
  if (amountCzk !== undefined && amountCzk !== null && amountCzk !== "") {
    secondary = formatCzk(amountCzk);
  } else if (estimateCzk && currency === "USD") {
    secondary = `≈ ${formatCzk(estimateCzkFromUsd(n))}`;
  } else if (currency === "CZK") {
    secondary = `≈ ${formatUsd(n / 23.1)}`;
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
