/**
 * The menu: every page in ACE, who may see it, and the one-line introduction the welcome tour uses for it
 * (docs/ACE-Guided-Onboarding-Engineering-Guide.md 4.1). Sidebar.tsx draws it; User Access previews it; the
 * welcome tour and Show me how read it - so the menu, the tour and the preview never disagree.
 */
import {
  BarChart3,
  BookOpen,
  Bot,
  CalendarDays,
  ClipboardList,
  ConciergeBell,
  Database,
  Factory,
  LayoutDashboard,
  MessageSquare,
  Package,
  ScrollText,
  Settings,
  Shield,
  ShoppingCart,
  Users,
  Workflow,
  Wrench,
} from "lucide-react";

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

export const NAV_DEFINED: NavItem[] = [
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
        { label: "Stock reports", href: "/stock-reports" },
        { label: "Quality Control", href: "/quality-control", roles: ["admin", "quality_assurance", "qa", "management"] },
        { label: "Compliance & QMS", href: "/compliance", roles: ["admin", "quality_assurance", "qa", "operations", "ops", "management"] },
      ],
    },
    {
      // Sage's Maintain menu: the records behind the books (items, batches, vendors, lists)
      label: "Maintain",
      icon: Wrench,
      roles: ["admin", "finance", "management", "ops", "operations", "procurement", "quality_assurance", "qa"],
      children: [
        { label: "Inventory Items", href: "/maintain?tab=items" },
        { label: "Batch numbers & dates", href: "/maintain?tab=batches" },
        { label: "Vendors", href: "/maintain?tab=vendors", roles: ["admin", "finance", "management"] },
        { label: "Shipping methods", href: "/maintain?tab=ship", roles: ["admin", "finance", "management"] },
        { label: "Customers, accounts & more", href: "/maintain?tab=more" },
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
/** Main folders in alphabetical order (client, 28 Oct); My Workspace - everyone's home - stays first. */
export const NAV_ITEMS: NavItem[] = [
  ...NAV_DEFINED.filter((i) => i.label === "My Workspace"),
  ...NAV_DEFINED.filter((i) => i.label !== "My Workspace").sort((a, b) => a.label.localeCompare(b.label, "en", { sensitivity: "base" })),
];

export function visibleNav(roles: string[]): { label: string; children: string[] }[] {
  const ok = (allowed?: string[]) => !allowed || allowed.length === 0 || roles.some((r) => allowed.includes(r));
  return NAV_ITEMS.filter((i) => ok(i.roles)).map((i) => ({
    label: i.label,
    children: (i.children ?? []).filter((c) => ok(c.roles)).map((c) => c.label),
  }));
}
