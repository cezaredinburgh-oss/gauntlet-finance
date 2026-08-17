/** Filenames must match year_end_export.py ZIP entries — do not invent files. */
const PACK_MEANING: Array<{ file: (year: number) => string; meaning: string }> = [
  { file: () => "tax-report.json", meaning: "Full tax report (lot allocations, open lots)" },
  {
    file: () => "taxable-disposals.csv",
    meaning: "Disposals that do not qualify for 3-year exemption",
  },
  { file: () => "exempt-disposals.csv", meaning: "Disposals that qualify" },
  { file: () => "open-lots.csv", meaning: "Open tax lots snapshot" },
  { file: () => "realized-by-year.csv", meaning: "Multi-year realised gain summary" },
  {
    file: (year) => `category-spend-${year}.csv`,
    meaning: "Cash expenses by category (USD, excl. internal transfers)",
  },
  { file: () => "statement-files.json", meaning: "Import audit log" },
  { file: () => "README.txt", meaning: "Pack methodology" },
];

export function TaxFilingKitLegend({ year }: { year: number }) {
  return (
    <ul className="mt-3 grid gap-1 text-[11px] text-ink-faint sm:grid-cols-2">
      {PACK_MEANING.map((entry) => {
        const name = entry.file(year);
        return (
          <li key={name} className="flex gap-2">
            <span className="shrink-0 font-mono text-ink-muted">{name}</span>
            <span>{entry.meaning}</span>
          </li>
        );
      })}
    </ul>
  );
}
