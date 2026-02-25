import { Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  DollarSign,
  BarChart3,
  FileText,
  Upload,
  Users,
  Settings,
  MessageSquare,
  Workflow,
  Factory,
  ShoppingCart,
  Zap,
  Shield,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "./AuthProvider";

const Sidebar = () => {
  const location = useLocation();
  const { roles } = useAuth();

  const isActive = (path: string) => location.pathname === path;
  const isActiveGroup = (paths: string[]) =>
    paths.some((p) => location.pathname.startsWith(p));

  const navItems = [
    {
      label: "Dashboard",
      icon: LayoutDashboard,
      href: "/",
      badge: null,
    },
    {
      label: "Executive Summary",
      icon: BarChart3,
      href: "/executive",
      roles: ["admin", "management"],
    },
    {
      label: "Finance",
      icon: DollarSign,
      roles: ["admin", "finance"],
      children: [
        { label: "Analytics", href: "/finance/analytics" },
        { label: "Reports", href: "/finance/reports" },
        { label: "Sage Import", href: "/finance/sage-import" },
      ],
    },
    {
      label: "HR",
      icon: Users,
      href: "/hr",
      roles: ["admin", "hr"],
    },
    {
      label: "Operations",
      icon: Factory,
      roles: ["admin", "ops", "operations"],
      href: "/operations",
      children: [
        { label: "Overview", href: "/operations" },
        { label: "Project Controls", href: "/operations/project-controls" },
      ],
    },
    {
      label: "CRM",
      icon: ShoppingCart,
      href: "/crm",
      roles: ["admin", "crm", "sales"],
    },
    {
      label: "Workflow",
      icon: Workflow,
      href: "/workflow",
      roles: ["admin"],
    },
    {
      label: "User Access",
      icon: Shield,
      href: "/admin/users",
      roles: ["admin"],
    },
    {
      label: "Ask Synbot",
      icon: MessageSquare,
      href: "/synbot",
      badge: "AI",
    },
    {
      label: "Settings",
      icon: Settings,
      href: "/settings",
      roles: ["admin"],
    },
  ];

  const canView = (allowed?: string[]) => {
    if (!allowed || allowed.length === 0) return true;
    return roles.some((role) => allowed.includes(role));
  };

  const visibleNavItems = navItems.filter((item) => canView((item as any).roles));

  return (
    <div className="fixed left-0 top-0 h-screen w-64 bg-primary text-primary-foreground flex flex-col">
      {/* Logo/Header */}
      <div className="p-6 border-b border-sidebar-border">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-accent rounded-lg flex items-center justify-center">
            <Zap className="w-6 h-6 text-accent-foreground" />
          </div>
          <div>
            <h1 className="font-bold text-lg">Synbot</h1>
            <p className="text-xs opacity-75">BVE</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-4 px-3">
        {visibleNavItems.map((item) => {
          const Icon = item.icon;
          const hasChildren = "children" in item;
          const isGroupActive =
            hasChildren && isActiveGroup(item.children!.map((c) => c.href));
          const itemActive = !hasChildren && isActive(item.href || "");

          return (
            <div key={item.label}>
              {hasChildren ? (
                <div className="mb-2">
                  <div className="text-xs font-semibold uppercase opacity-50 px-3 py-2">
                    {item.label}
                  </div>
                  <div className="space-y-1">
                    {item.children!.map((child) => (
                      <Link
                        key={child.href}
                        to={child.href}
                        className={cn(
                          "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors",
                          isActive(child.href)
                            ? "bg-sidebar-accent text-sidebar-accent-foreground"
                            : "text-primary-foreground hover:bg-sidebar-accent hover:bg-opacity-20"
                        )}
                      >
                        <div className="w-1 h-1 rounded-full" />
                        {child.label}
                      </Link>
                    ))}
                  </div>
                </div>
              ) : (
                <Link
                  to={item.href || "/"}
                  className={cn(
                    "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors mb-1",
                    itemActive
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "text-primary-foreground hover:bg-sidebar-accent hover:bg-opacity-20"
                  )}
                >
                  <Icon className="w-4 h-4" />
                  <span className="flex-1">{item.label}</span>
                  {item.badge && (
                    <span className="px-2 py-0.5 bg-accent text-accent-foreground text-xs rounded-full font-semibold">
                      {item.badge}
                    </span>
                  )}
                </Link>
              )}
            </div>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-sidebar-border text-xs opacity-60">
        <p>Placeware Nigeria</p>
        <p>Enterprise Admin</p>
      </div>
    </div>
  );
};

export default Sidebar;
