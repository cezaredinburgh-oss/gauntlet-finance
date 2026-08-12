import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

/** Persistent notice while signed in as a public demo principal. */
export function DemoBanner() {
  const { user, logout, isReadOnly } = useAuth();
  if (!user?.is_demo) return null;

  const kind = user.demo_kind === "tour" ? "tour" : "sandbox";
  const title = kind === "tour" ? "Sample portfolio" : "Sandbox";
  const body =
    kind === "tour"
      ? "Read-only synthetic data — explore freely; uploads and edits are disabled."
      : "Empty session ledger — try uploads here. Data clears when you sign out.";

  return (
    <div
      className={
        isReadOnly
          ? "border-b border-sky-400/30 bg-sky-400/10 px-4 py-2 text-center text-xs text-sky-100 sm:text-sm"
          : "border-b border-amber-400/30 bg-amber-400/10 px-4 py-2 text-center text-xs text-amber-100 sm:text-sm"
      }
    >
      <strong className="font-semibold">{title}</strong>
      <span className={isReadOnly ? "text-sky-100/90" : "text-amber-100/90"}>
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
      <span className={isReadOnly ? "mx-1 text-sky-100/50" : "mx-1 text-amber-100/50"}>·</span>
      <Link to="/login" className="font-medium underline underline-offset-2">
        Landing
      </Link>
    </div>
  );
}
