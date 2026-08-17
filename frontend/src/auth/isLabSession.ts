import type { AuthMe } from "../api/types";

export function isLabSession(
  user: Pick<AuthMe, "is_demo" | "demo_kind"> | null | undefined,
): boolean {
  return Boolean(user?.is_demo && user.demo_kind === "lab");
}
