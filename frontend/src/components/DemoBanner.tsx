import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

/** Persistent notice while signed in as the demo principal. */
export function DemoBanner() {
  const { user, logout } = useAuth();
  if (!user?.is_demo) return null;

  return (
    <div className="border-b border-amber-400/30 bg-amber-400/10 px-4 py-2 text-center text-xs text-amber-100 sm:text-sm">
      <strong className="font-semibold">Demo mode</strong>
      <span className="text-amber-100/90">
        {" "}
        — isolated sample ledger, not your real finances.{" "}
      </span>
      <button
        type="button"
        className="font-medium underline underline-offset-2"
        onClick={() => void logout()}
      >
        Sign out
      </button>
      <span className="mx-1 text-amber-100/50">·</span>
      <Link to="/login" className="font-medium underline underline-offset-2">
        Landing
      </Link>
    </div>
  );
}
