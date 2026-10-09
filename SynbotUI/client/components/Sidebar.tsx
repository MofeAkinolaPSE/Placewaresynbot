import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTheme } from "next-themes";
import {
  LayoutDashboard,
  DollarSign,
  BookOpen,
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
  Database,
  Package,
  ConciergeBell,
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

export type NavChild = { label: string; href: string; roles?: string[] };

export type NavItem = {
  label: string;
  icon: React.ElementType;
  href?: string;
  badge?: string;
  roles?: string[];
  children?: NavChild[];
  aiPulse?: boolean;
};

export const NAV_ITEMS: NavItem[] = [
    {
      // Everyone's home: day, tasks, requests, messages, work clock, progress.
      label: "My Workspace",
      icon: ClipboardList,
      href: "/workspace",
    },
    {
      label: "Dashboard",
      icon: LayoutDashboard,
      href: "/",
    },
    {
      label: "Executive Overview",
      icon: BarChart3,
      href: "/executive",
      roles: ["admin", "management", "finance"],
    },
    {
      label: "ACE Books",
      icon: BookOpen,
      roles: ["admin", "finance", "management"],
      children: [
        { label: "Finance Control Tower", href: "/finance/books" },
        { label: "Sales & Receivables", href: "/finance/books/sales" },
        { label: "Invoice Register", href: "/finance/books/sales?tab=register" },
        { label: "Purchases & Payables", href: "/finance/books/purchases" },
        { label: "Stock", href: "/finance/books/stock" },
        { label: "Banking", href: "/finance/books/banking" },
        { label: "Journals & Ledger", href: "/finance/books/ledger" },
        { label: "Financial Statements", href: "/finance/books/statements" },
        { label: "Report Center", href: "/finance/books/reports" },
        { label: "Credit Control & Alerts", href: "/finance/ar" },
        { label: "Fixed Assets", href: "/finance/books/assets" },
        { label: "Close & Controls", href: "/finance/books/close" },
        { label: "Setup & Migration", href: "/finance/books/setup" },
        { label: "Sage Import / Export", href: "/finance/sage-import" },
      ],
    },
    {
      label: "HR",
      icon: Users,
      href: "/hr",
      roles: ["admin", "hr", "management"],
    },
    {
      // Stock, quality control and compliance are one department: they act on the same
      // batches and stock, all recorded in ACE Books (see services/quality_hub.py).
      label: "Inventory & Quality",
      icon: Package,
      roles: ["admin", "ops", "operations", "procurement", "finance", "sales", "quality_assurance", "qa", "management"],
      children: [
        { label: "Overview", href: "/quality" },
        { label: "Stock", href: "/inventory" },
        { label: "Quality Control", href: "/quality-control", roles: ["admin", "quality_assurance", "qa", "management"] },
        { label: "Compliance & QMS", href: "/compliance", roles: ["admin", "quality_assurance", "qa", "operations", "ops", "management"] },
      ],
    },
    {
      label: "Operations",
      icon: Factory,
      roles: ["admin", "ops", "operations", "procurement", "management"],
      children: [
        { label: "Overview", href: "/operations" },
        { label: "Project Controls", href: "/operations/project-controls", roles: ["admin", "ops", "operations", "management"] },
        { label: "Suppliers", href: "/operations/suppliers" },
        { label: "Stock Orders & Purchases", href: "/operations/purchase-orders" },
        { label: "Logistics Monitor", href: "/operations/logistics" },
      ],
    },
    {
      label: "CRM",
      icon: ShoppingCart,
      // "crm" is not in the backend's ALLOWED_ROLES (app.py) and is not
      // assignable from AdminUsers, so gating on it alone hid this whole
      // section from every role except admin/sales.
      roles: ["admin", "sales", "management", "finance"],
      children: [
        { label: "Overview", href: "/crm" },
        { label: "Customers", href: "/crm/customers" },
        { label: "Customer Workspace", href: "/customers/workspace" },
        { label: "Sales Pipeline", href: "/crm/sales" },
        { label: "Leads & Prospecting", href: "/crm/lead-finder" },
      ],
    },
    {
      // Its own department with its own role. Walk-ins, requests and stock checks need
      // only a login; the QC, finance and dispatch steps inside keep their own gates,
      // so everyone who works that pipeline also sees it.
      label: "Frontdesk",
      icon: ConciergeBell,
      href: "/frontdesk",
      roles: ["admin", "frontdesk", "management", "sales", "finance", "ops", "operations", "quality_assurance", "qa"],
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
      label: "Data Intelligence",
      icon: Database,
      href: "/admin/data-intelligence",
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
      // everyone who owns records they may need to report on
      roles: ["admin", "management", "finance", "manager", "quality_assurance", "qa", "ops", "operations", "procurement", "sales", "hr", "frontdesk"],
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

/** What a set of roles sees in the sidebar - also used by User Access to preview a new account. */
export function visibleNav(roles: string[]): { label: string; children: string[] }[] {
  const ok = (allowed?: string[]) => !allowed || allowed.length === 0 || roles.some((r) => allowed.includes(r));
  return NAV_ITEMS.filter((i) => ok(i.roles)).map((i) => ({
    label: i.label,
    children: (i.children ?? []).filter((c) => ok(c.roles)).map((c) => c.label),
  }));
}

const Sidebar = ({ mobileOpen, onMobileClose }: SidebarProps) => {
  const location = useLocation();
  const { roles, logout } = useAuth();

  // Track which collapsible groups are open
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});

  // a link may carry a tab (e.g. /finance/books/sales?tab=register): active when that tab is open
  const isActive = (path: string) => {
    const [p, qs] = path.split("?");
    return location.pathname === p && (!qs || location.search.includes(qs));
  };
  const isActiveGroup = (paths: string[]) =>
    paths.some((p) => location.pathname.startsWith(p));


  const canView = (allowed?: string[]) => {
    if (!allowed || allowed.length === 0) return true;
    return roles.some((role) => allowed.includes(role));
  };

  const visibleNavItems = NAV_ITEMS.filter((item) => canView(item.roles));

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
          "fixed left-0 top-0 z-30 flex h-dvh w-64 flex-col pl-[env(safe-area-inset-left)] border-r border-sidebar-border/70 bg-sidebar/95 text-sidebar-foreground backdrop-blur-lg transition-transform duration-300",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
          "lg:translate-x-0",
        )}
      >
        {/* Logo/Header */}
        <div className="pw-safe-top relative border-b border-sidebar-border/60 px-5 pb-4">
          {/* Soft brand halo behind the mark -- no card, no border, so the
              transparent logo sits directly on the sidebar instead of
              floating in a white box. */}
          <div
            className="pointer-events-none absolute inset-0"
            aria-hidden
            style={{
              background:
                "radial-gradient(ellipse 78% 90% at 30% 45%, rgba(98,199,106,0.14) 0%, transparent 70%)," +
                "radial-gradient(ellipse 60% 80% at 85% 20%, rgba(255,255,255,0.08) 0%, transparent 72%)",
            }}
          />
          <img
            src="/placeware-logo-onDark.png"
            alt="Placeware Nigeria Limited"
            className="relative h-auto w-full max-w-[190px] object-contain"
            style={{
              maxHeight: "46px",
              filter: "drop-shadow(0 1px 6px rgba(0,0,0,0.45))",
            }}
          />
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto px-2 py-3 scrollbar-thin">
          <div className="space-y-0.5">
            {visibleNavItems.map((item) => {
              const Icon = item.icon;
              const hasChildren = !!item.children;
              const childActive = hasChildren
                ? isActiveGroup(item.children!.map((c) => c.href))
                : false;
              // A group opens by itself while one of its pages is showing, until the user closes it.
              const groupOpen = openGroups[item.label] ?? childActive;
              const itemActive = !hasChildren && isActive(item.href ?? "");

              if (hasChildren) {
                return (
                  <Collapsible
                    key={item.label}
                    open={groupOpen}
                    onOpenChange={(o) => setOpenGroups((prev) => ({ ...prev, [item.label]: o }))}
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
                        {item.children!.filter((c) => !c.roles || roles.some((r) => c.roles!.includes(r))).map((child) => (
                          <Link
                            key={child.href}
                            to={child.href}
                            onClick={onMobileClose}
                            className={cn(
                              "relative flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition-all duration-150",
                              isActive(child.href)
                                ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium shadow-elevation-1 before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-sidebar-primary"
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
                    "relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-all duration-200 ease-out",
                    // Active item gets a brand-green rail on its left edge --
                    // the palette's second colour doing the wayfinding.
                    itemActive
                      ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-elevation-1 before:absolute before:inset-y-1.5 before:left-0 before:w-1 before:rounded-full before:bg-sidebar-primary"
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
        <div className="pw-safe-bottom border-t border-sidebar-border/80 p-3">
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
