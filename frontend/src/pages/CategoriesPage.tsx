import { Navigate, useLocation } from "react-router-dom";

/** Legacy route — unified into Categorize (rules panel). */
export function CategoriesPage() {
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  if (!params.has("panel")) params.set("panel", "rules");
  const q = params.toString();
  return <Navigate to={`/expenses/categorize${q ? `?${q}` : ""}`} replace />;
}
