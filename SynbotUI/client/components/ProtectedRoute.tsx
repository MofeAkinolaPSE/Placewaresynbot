import { PropsWithChildren } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthProvider";

const ProtectedRoute = ({ children }: PropsWithChildren) => {
  const { isAuthenticated, isLoading, roles } = useAuth();
  const location = useLocation();

  const hasRole = (allowed: string[]) => roles.some((role) => allowed.includes(role));

  const accessMap: Array<{ startsWith: string; allowed: string[] }> = [
    // ACE Books: management reviews, approves and reopens periods (backend ROLE_PERMISSIONS).
    // Must precede the broader /finance rule - the first match wins.
    { startsWith: "/finance/books", allowed: ["admin", "finance", "management"] },
    { startsWith: "/finance/ar", allowed: ["admin", "finance", "management"] },
    { startsWith: "/finance/sage-import", allowed: ["admin", "finance", "management"] },
    { startsWith: "/finance", allowed: ["admin", "finance"] },
    { startsWith: "/hr", allowed: ["admin", "hr", "management"] },
    { startsWith: "/operations", allowed: ["admin", "ops", "operations", "procurement", "management"] },
    { startsWith: "/inventory", allowed: ["admin", "ops", "operations", "procurement", "finance", "sales", "quality_assurance", "qa", "management"] },
    { startsWith: "/frontdesk", allowed: ["admin", "frontdesk", "management", "sales", "finance", "ops", "operations", "quality_assurance", "qa"] },
    { startsWith: "/crm", allowed: ["admin", "crm", "sales", "management", "finance"] },
    // /customers/workspace previously had no route-level gate at all (nav-
    // adjacent to the CRM group but never enforced by URL).
    { startsWith: "/customers", allowed: ["admin", "crm", "sales", "management", "finance"] },
    { startsWith: "/workflow", allowed: ["admin"] },
    { startsWith: "/admin/users", allowed: ["admin"] },
    { startsWith: "/admin/data-intelligence", allowed: ["admin"] },
    { startsWith: "/settings", allowed: ["admin"] },
    { startsWith: "/executive", allowed: ["admin", "management", "finance"] },
    // Previously had no route entry at all -- nav-gated via Sidebar.tsx but
    // reachable by anyone authenticated who typed the URL directly.
    { startsWith: "/quality-control", allowed: ["admin", "quality_assurance", "qa", "management"] },
    // Reconciled to match constants.COMPLIANCE_OPS_ROLES (the backend's own
    // established set for this exact domain) -- was ["admin","quality",
    // "quality_assurance","qa","ops"], which both included an orphan
    // "quality" string assignable by nobody and excluded "operations"/
    // "management", which the backend already allows. Sidebar.tsx's own
    // Compliance nav item is reconciled to the same set alongside this.
    { startsWith: "/compliance", allowed: ["admin", "quality_assurance", "qa", "operations", "ops", "management"] },
    // Inventory & Quality overview (after /quality-control, which is narrower).
    { startsWith: "/quality", allowed: ["admin", "ops", "operations", "procurement", "finance", "sales", "quality_assurance", "qa", "management"] },
  ];

  if (isLoading) {
    return (
      <div className="pw-page-surface min-h-dvh flex items-center justify-center text-muted-foreground">
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
