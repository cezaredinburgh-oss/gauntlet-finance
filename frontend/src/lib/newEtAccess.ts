/**
 * New ET is a UI fork of Expense tracking for the lab principal only.
 * Lab login is demo_kind === "lab" (LAB_EMAIL, default testaccount@o2.pl).
 * Sandbox and tour must never see this nav or these routes.
 */
export function isNewEtUser(
  user: { demo_kind?: string | null } | null | undefined,
): boolean {
  return user?.demo_kind === "lab";
}
