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
  CalendarDays,
  Bot,
  ClipboardList,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "./AuthProvider";

type SidebarProps = {
  mobileOpen: boolean;
  onMobileClose: () => void;
};

const Sidebar = ({ mobileOpen, onMobileClose }: SidebarProps) => {
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
      label: "Staff Dashboard",
      icon: ClipboardList,
      roles: ["admin", "hr", "ops", "management"],
      children: [
        { label: "Dashboard", href: "/staff/dashboard" },
        { label: "Collaboration", href: "/staff/collaboration" },
      ],
    },
    {
      label: "Operations",
      icon: Factory,
      roles: ["admin", "ops", "operations"],
      href: "/operations",
      children: [
        { label: "Overview", href: "/operations" },
        { label: "Project Controls", href: "/operations/project-controls" },
        { label: "Suppliers", href: "/operations/suppliers" },
      ],
    },
    {
      label: "CRM",
      icon: ShoppingCart,
      roles: ["admin", "crm", "sales"],
      children: [
        { label: "Overview", href: "/crm" },
        { label: "Lead Finder", href: "/crm/lead-finder" },
        { label: "Leads", href: "/admin/leads" },
      ],
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
      label: "Ask PlacewareBot",
      icon: MessageSquare,
      href: "/synbot",
      badge: "AI",
    },
    {
      label: "Calendar & Tasks",
      icon: CalendarDays,
      href: "/calendar",
    },
    {
      label: "Agent Stack",
      icon: Bot,
      href: "/agents",
      badge: "AI",
      roles: ["admin", "management"],
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
    <>
      <div
        className={cn(
          "fixed inset-0 z-20 bg-black/40 transition-opacity lg:hidden",
          mobileOpen ? "opacity-100" : "pointer-events-none opacity-0",
        )}
        onClick={onMobileClose}
      />
      <div
        className={cn(
          "fixed left-0 top-0 z-30 flex h-screen w-64 flex-col border-r border-sidebar-border/70 bg-sidebar/95 text-sidebar-foreground backdrop-blur-lg transition-transform duration-300",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
          "lg:translate-x-0",
        )}
      >
      {/* Logo/Header */}
      <div className="border-b border-sidebar-border/80 p-6">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-primary shadow-elevation-2">
            <Zap className="w-6 h-6 text-accent-foreground" />
          </div>
          <div>
            <h1 className="text-lg font-bold">PlacewareBot</h1>
            <p className="text-xs opacity-70">Enterprise Intelligence</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-4">
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
                  <div className="px-3 py-2 text-xs font-semibold uppercase tracking-wide opacity-55">
                    {item.label}
                  </div>
                  <div className="space-y-1">
                    {item.children!.map((child) => (
                      <Link
                        key={child.href}
                        to={child.href}
                        onClick={onMobileClose}
                        className={cn(
                          "flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-all duration-200 ease-smooth",
                          isActive(child.href)
                            ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-elevation-1"
                            : "text-sidebar-foreground/90 hover:bg-sidebar-accent/60"
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
                  onClick={onMobileClose}
                  className={cn(
                    "mb-1 flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-all duration-200 ease-smooth",
                    itemActive
                      ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-elevation-1"
                      : "text-sidebar-foreground/90 hover:bg-sidebar-accent/60"
                  )}
                >
                  <Icon className="w-4 h-4" />
                  <span className="flex-1">{item.label}</span>
                  {item.badge && (
                    <span className="rounded-full bg-gradient-primary px-2 py-0.5 text-xs font-semibold text-primary-foreground">
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
      <div className="border-t border-sidebar-border/80 p-4 text-xs opacity-60">
        <p>Placeware Nigeria</p>
        <p>Enterprise Console</p>
      </div>
      </div>
    </>
  );
};

export default Sidebar;
