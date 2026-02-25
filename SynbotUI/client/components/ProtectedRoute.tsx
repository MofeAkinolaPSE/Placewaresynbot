import { PropsWithChildren } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthProvider";

const ProtectedRoute = ({ children }: PropsWithChildren) => {
  const { isAuthenticated, isLoading, roles } = useAuth();
  const location = useLocation();

  const hasRole = (allowed: string[]) => roles.some((role) => allowed.includes(role));

  const accessMap: Array<{ startsWith: string; allowed: string[] }> = [
    { startsWith: "/finance", allowed: ["admin", "finance"] },
    { startsWith: "/hr", allowed: ["admin", "hr"] },
    { startsWith: "/operations", allowed: ["admin", "ops", "operations"] },
    { startsWith: "/crm", allowed: ["admin", "crm", "sales"] },
    { startsWith: "/workflow", allowed: ["admin"] },
    { startsWith: "/admin/users", allowed: ["admin"] },
    { startsWith: "/settings", allowed: ["admin"] },
    { startsWith: "/executive", allowed: ["admin", "management"] },
  ];

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-slate-600">
        Loading…
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  const matched = accessMap.find((rule) => location.pathname.startsWith(rule.startsWith));
  if (matched && !hasRole(matched.allowed)) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
};

export default ProtectedRoute;
