import { Navigate, useLocation } from "react-router-dom";

/** Legacy route — unified into Categorize. */
export function TransactionsPage() {
  const { search } = useLocation();
  return <Navigate to={`/expenses/categorize${search}`} replace />;
}
