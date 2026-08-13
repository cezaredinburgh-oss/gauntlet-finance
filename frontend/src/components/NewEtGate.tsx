import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { isNewEtUser } from "../lib/newEtAccess";

/** Block /new-et/* for every account that is not the lab principal. */
export function NewEtGate({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (!isNewEtUser(user)) {
    return <Navigate to="/expenses/spending" replace />;
  }
  return <>{children}</>;
}
