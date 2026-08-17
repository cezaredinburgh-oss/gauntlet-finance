export type HonestyChipKind = "internals" | "unconverted" | "uncat";

export type HonestyChip = {
  kind: HonestyChipKind;
  label: string;
};

export type HonestyModel = {
  chips: HonestyChip[];
  /** Distinct card when uncategorized_pct >= 70 — never a quiet chip. */
  uncatCard: boolean;
};

function formatUncatPct(n: number): string {
  const rounded = Math.round(n * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}

/**
 * Quiet honesty only. Internals / unconverted when count > 0.
 * Uncat 20–69.9 is a chip; ≥70 is the card (not this list); <20 is silent.
 */
export function honestyChips(input: {
  internalTransferCount?: number | null;
  unconvertedCount?: number | null;
  uncategorizedPct?: number | null;
}): HonestyModel {
  const internals = input.internalTransferCount ?? 0;
  const unconverted = input.unconvertedCount ?? 0;
  const uncat = input.uncategorizedPct ?? 0;
  const chips: HonestyChip[] = [];

  if (internals > 0) {
    chips.push({
      kind: "internals",
      label: `${internals} internals excluded`,
    });
  }
  if (unconverted > 0) {
    chips.push({
      kind: "unconverted",
      label: `${unconverted} unconverted`,
    });
  }

  const uncatCard = uncat >= 70;
  if (uncat >= 20 && uncat < 70) {
    chips.push({
      kind: "uncat",
      label: `${formatUncatPct(uncat)}% uncategorized`,
    });
  }

  return { chips, uncatCard };
}
