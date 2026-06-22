import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTheme } from "next-themes";
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
  Shield,
  ShieldCheck,
  CalendarDays,
  Bot,
  ClipboardList,
  Timer,
  ChevronDown,
  ChevronRight,
  LogOut,
  MoreVertical,
  Sun,
  Moon,
  ScrollText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "./AuthProvider";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type SidebarProps = {
  mobileOpen: boolean;
  onMobileClose: () => void;
};

type NavChild = { label: string; href: string };

type NavItem = {
  label: string;
  icon: React.ElementType;
  href?: string;
  badge?: string;
  roles?: string[];
  children?: NavChild[];
  aiPulse?: boolean;
};

const Sidebar = ({ mobileOpen, onMobileClose }: SidebarProps) => {
  const location = useLocation();
  const { roles, logout } = useAuth();

  // Track which collapsible groups are open
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});

  const toggleGroup = (label: string) => {
    setOpenGroups((prev) => ({ ...prev, [label]: !prev[label] }));
  };

  const isActive = (path: string) => location.pathname === path;
  const isActiveGroup = (paths: string[]) =>
    paths.some((p) => location.pathname.startsWith(p));

  const navItems: NavItem[] = [
    {
      label: "Dashboard",
      icon: LayoutDashboard,
      href: "/",
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
        { label: "AR & Alerts", href: "/finance/ar" },
        { label: "Vendor Payments", href: "/finance/vendor-payments" },
        { label: "Budget", href: "/finance/budget" },
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
        { label: "Time Tracker", href: "/staff/time-tracker" },
        { label: "Collaboration", href: "/staff/collaboration" },
      ],
    },
    {
      label: "Operations",
      icon: Factory,
      roles: ["admin", "ops", "operations"],
      children: [
        { label: "Overview", href: "/operations" },
        { label: "Project Controls", href: "/operations/project-controls" },
        { label: "Suppliers", href: "/operations/suppliers" },
        { label: "Purchase Orders", href: "/operations/purchase-orders" },
        { label: "Logistics Monitor", href: "/operations/logistics" },
      ],
    },
    {
      label: "CRM",
      icon: ShoppingCart,
      roles: ["admin", "crm", "sales"],
      children: [
        { label: "Overview", href: "/crm" },
        { label: "Sales Pipeline", href: "/crm/sales" },
        { label: "Lead Finder", href: "/crm/lead-finder" },
        { label: "Leads", href: "/admin/leads" },
        { label: "Frontdesk", href: "/frontdesk" },
      ],
    },
    {
      label: "Compliance & QMS",
      icon: ShieldCheck,
      href: "/compliance",
      roles: ["admin", "quality_assurance", "qa", "management"],
    },
    {
      label: "Quality Control",
      icon: ClipboardList,
      href: "/quality-control",
      roles: ["admin", "quality_assurance", "qa", "management"],
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
      label: "Ask ACE",
      icon: MessageSquare,
      href: "/synbot",
      badge: "AI",
      aiPulse: true,
    },
    {
      label: "Agent Stack",
      icon: Bot,
      href: "/agents",
      badge: "AI",
      aiPulse: true,
      roles: ["admin", "management"],
    },
    {
      label: "Logistics Calendar",
      icon: CalendarDays,
      href: "/calendar",
    },
    {
      label: "Reports",
      icon: ScrollText,
      roles: ["admin", "management", "finance", "manager"],
      children: [
        { label: "Generate Report", href: "/reports/new" },
        { label: "Report Library", href: "/reports" },
      ],
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

  const visibleNavItems = navItems.filter((item) => canView(item.roles));

  const { theme, setTheme } = useTheme();
  const isDark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);

  // Derive user initials from roles/auth — fallback to "PW"
  const userRole = roles[0] ?? "user";
  const initials = userRole.slice(0, 2).toUpperCase();

  return (
    <>
      {/* Mobile overlay */}
      <div
        className={cn(
          "fixed inset-0 z-20 bg-black/40 transition-opacity lg:hidden",
          mobileOpen ? "opacity-100" : "pointer-events-none opacity-0",
        )}
        onClick={onMobileClose}
      />

      {/* Sidebar panel */}
      <div
        className={cn(
          "fixed left-0 top-0 z-30 flex h-screen w-64 flex-col border-r border-sidebar-border/70 bg-sidebar/95 text-sidebar-foreground backdrop-blur-lg transition-transform duration-300",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
          "lg:translate-x-0",
        )}
      >
        {/* Logo/Header */}
        <div className="border-b border-sidebar-border/80 px-4 py-3.5">
          <div
            className="relative overflow-hidden rounded-xl px-3 py-2"
            style={{
              background: "linear-gradient(135deg, rgba(0,200,220,0.07) 0%, rgba(0,90,200,0.05) 100%)",
              border: "1px solid rgba(0,200,220,0.15)",
              boxShadow: "0 0 18px rgba(0,200,220,0.08), inset 0 1px 0 rgba(255,255,255,0.06)",
            }}
          >
            {/* Radial highlight shimmer */}
            <div
              className="pointer-events-none absolute inset-0"
              aria-hidden
              style={{
                background: "radial-gradient(ellipse 70% 55% at 50% 0%, rgba(255,255,255,0.07) 0%, transparent 70%)",
              }}
            />
            <img
              src="/placeware-logo.jpg"
              alt="Placeware Nigeria Limited"
              className="relative w-full h-auto object-contain"
              style={{
                maxHeight: "48px",
                filter: "drop-shadow(0 2px 8px rgba(0,200,220,0.28)) drop-shadow(0 0 2px rgba(255,255,255,0.15))",
              }}
            />
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto px-2 py-3 scrollbar-thin">
          <div className="space-y-0.5">
            {visibleNavItems.map((item) => {
              const Icon = item.icon;
              const hasChildren = !!item.children;
              const groupOpen = !!openGroups[item.label];
              const childActive = hasChildren
                ? isActiveGroup(item.children!.map((c) => c.href))
                : false;
              const itemActive = !hasChildren && isActive(item.href ?? "");

              if (hasChildren) {
                return (
                  <Collapsible
                    key={item.label}
                    open={groupOpen}
                    onOpenChange={() => toggleGroup(item.label)}
                  >
                    <CollapsibleTrigger asChild>
                      <button
                        className={cn(
                          "flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-all duration-200 ease-out",
                          childActive
                            ? "bg-sidebar-accent/70 text-sidebar-accent-foreground"
                            : "text-sidebar-foreground/80 hover:bg-sidebar-accent/40 hover:text-sidebar-foreground",
                        )}
                      >
                        <Icon className="h-4 w-4 shrink-0" />
                        <span className="flex-1 text-left">{item.label}</span>
                        <ChevronDown
                          className={cn(
                            "h-3.5 w-3.5 shrink-0 opacity-50 transition-transform duration-200",
                            groupOpen && "rotate-180",
                          )}
                        />
                      </button>
                    </CollapsibleTrigger>
                    <CollapsibleContent className="overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
                      <div className="ml-3 mt-0.5 space-y-0.5 border-l border-sidebar-border/50 pl-3 pb-1">
                        {item.children!.map((child) => (
                          <Link
                            key={child.href}
                            to={child.href}
                            onClick={onMobileClose}
                            className={cn(
                              "flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition-all duration-150",
                              isActive(child.href)
                                ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium shadow-elevation-1"
                                : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
                            )}
                          >
                            <span className="h-1 w-1 rounded-full bg-current opacity-50" />
                            {child.label}
                          </Link>
                        ))}
                      </div>
                    </CollapsibleContent>
                  </Collapsible>
                );
              }

              return (
                <Link
                  key={item.label}
                  to={item.href ?? "/"}
                  onClick={onMobileClose}
                  className={cn(
                    "flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-all duration-200 ease-out",
                    itemActive
                      ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-elevation-1"
                      : "text-sidebar-foreground/80 hover:bg-sidebar-accent/40 hover:text-sidebar-foreground",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="flex-1">{item.label}</span>
                  {item.aiPulse && (
                    <span className="relative flex h-2 w-2">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
                      <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
                    </span>
                  )}
                  {item.badge && !item.aiPulse && (
                    <span className="rounded-full bg-gradient-primary px-2 py-0.5 text-[10px] font-semibold text-primary-foreground">
                      {item.badge}
                    </span>
                  )}
                </Link>
              );
            })}
          </div>
        </nav>

        {/* User Profile Footer */}
        <div className="border-t border-sidebar-border/80 p-3">
          <div className="flex items-center gap-2 rounded-xl px-2 py-2 hover:bg-sidebar-accent/40 transition-colors duration-150">
            {/* Avatar */}
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-primary text-xs font-bold text-primary-foreground shadow-elevation-1">
              {initials}
            </div>
            {/* Name + role */}
            <div className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-sm font-medium leading-tight">
                ACE
              </span>
              <span className="truncate text-[11px] capitalize text-sidebar-foreground/50 leading-tight">
                {userRole}
              </span>
            </div>
            {/* Actions dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  className="ml-auto flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-sidebar-foreground/50 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground transition-colors"
                  aria-label="User options"
                >
                  <MoreVertical className="h-4 w-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="end"
                side="top"
                sideOffset={8}
                className="w-48"
              >
                <DropdownMenuItem asChild>
                  <Link to="/settings">
                    <Settings className="mr-2 h-4 w-4" />
                    Settings
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => setTheme(isDark ? "light" : "dark")}
                >
                  {isDark ? (
                    <Sun className="mr-2 h-4 w-4" />
                  ) : (
                    <Moon className="mr-2 h-4 w-4" />
                  )}
                  {isDark ? "Light mode" : "Dark mode"}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onClick={() => logout()}
                >
                  <LogOut className="mr-2 h-4 w-4" />
                  Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>
    </>
  );
};

export default Sidebar;
