import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

/** Persistent notice while signed in as a public demo principal. */
export function DemoBanner() {
  const { user, logout } = useAuth();
  if (!user?.is_demo) return null;

  const kind =
    user.demo_kind === "tour"
      ? "tour"
      : user.demo_kind === "lab"
        ? "lab"
        : "sandbox";
  const title =
    kind === "tour" ? "Sample portfolio" : kind === "lab" ? "Lab account" : "Sandbox";
  const body =
    kind === "tour"
      ? "Read-only synthetic data — explore freely; uploads and edits are disabled."
      : kind === "lab"
        ? "Persistent test ledger (disk) — full app; data survives sign-out. Not Google Sheets."
        : "Empty session ledger — try uploads here. Data clears when you sign out.";

  const tone =
    kind === "tour"
      ? {
          bar: "border-b border-sky-400/30 bg-sky-400/10 px-4 py-2 text-center text-xs text-sky-100 sm:text-sm",
          muted: "text-sky-100/90",
          sep: "mx-1 text-sky-100/50",
        }
      : kind === "lab"
        ? {
            bar: "border-b border-emerald-400/30 bg-emerald-400/10 px-4 py-2 text-center text-xs text-emerald-100 sm:text-sm",
            muted: "text-emerald-100/90",
            sep: "mx-1 text-emerald-100/50",
          }
        : {
            bar: "border-b border-amber-400/30 bg-amber-400/10 px-4 py-2 text-center text-xs text-amber-100 sm:text-sm",
            muted: "text-amber-100/90",
            sep: "mx-1 text-amber-100/50",
          };

  return (
    <div className={tone.bar}>
      <strong className="font-semibold">{title}</strong>
      <span className={tone.muted}>
        {" "}
        — {body}{" "}
      </span>
      <button
        type="button"
        className="font-medium underline underline-offset-2"
        onClick={() => void logout()}
      >
        Sign out
      </button>
      <span className={tone.sep}>·</span>
      <Link to="/login" className="font-medium underline underline-offset-2">
        Landing
      </Link>
    </div>
  );
}
