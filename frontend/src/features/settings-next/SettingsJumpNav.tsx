import { SETTINGS_NAV } from "./settingsNav";

/** In-flow hash nav — not sticky (same lesson as LabNextChrome). */
export function SettingsJumpNav() {
  return (
    <nav
      aria-label="Settings sections"
      className="flex min-w-0 flex-wrap gap-2"
    >
      {SETTINGS_NAV.map((item) => (
        <a
          key={item.id}
          href={`#${item.id}`}
          className="inline-flex items-center rounded-lg bg-white/5 px-2.5 py-1 text-xs font-medium text-ink-muted hover:bg-white/10 hover:text-ink"
        >
          {item.label}
        </a>
      ))}
    </nav>
  );
}
