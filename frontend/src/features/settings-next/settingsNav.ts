/** Jump-nav ids. Admin is omitted — gated separately after #storage. */
export const SETTINGS_NAV = [
  { id: "account", label: "Account" },
  { id: "display", label: "Display" },
  { id: "storage", label: "Storage" },
  { id: "ai", label: "AI" },
  { id: "export", label: "Export" },
  { id: "jobs", label: "Jobs" },
  { id: "danger", label: "Danger" },
] as const;

export type SettingsNavId = (typeof SETTINGS_NAV)[number]["id"];
