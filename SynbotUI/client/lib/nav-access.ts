/**
 * Who may open what - one rule for the route guard (ProtectedRoute), the menu, User Access's preview, the welcome
 * tour and Show me how (docs/ACE-Guided-Onboarding-Engineering-Guide.md 4.1). Links may carry a tab
 * ("/finance/books/sales?tab=register"): access is decided on the path alone, the query is kept for navigation.
 */
import { NAV_ITEMS, type NavChild, type NavItem } from "./nav-items";

/** Route rules, first match wins (moved unchanged from ProtectedRoute, plus the shared invoice print page). */
export const ROUTE_ACCESS: Array<{ startsWith: string; allowed: string[] }> = [
  // The printed invoice is one page for every invoice (ACE Books and Frontdesk): whoever can raise or follow an
  // invoice prints it. Must precede /finance/books, or Frontdesk and Sales were sent back to the Dashboard.
  { startsWith: "/finance/books/invoice-print", allowed: ["admin", "finance", "management", "frontdesk", "sales", "ops", "operations", "quality_assurance", "qa", "crm"] },
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
  { startsWith: "/customers", allowed: ["admin", "crm", "sales", "management", "finance"] },
  { startsWith: "/workflow", allowed: ["admin"] },
  { startsWith: "/admin/users", allowed: ["admin"] },
  { startsWith: "/admin/data-intelligence", allowed: ["admin"] },
  { startsWith: "/settings", allowed: ["admin"] },
  { startsWith: "/executive", allowed: ["admin", "management", "finance"] },
  { startsWith: "/quality-control", allowed: ["admin", "quality_assurance", "qa", "management"] },
  { startsWith: "/compliance", allowed: ["admin", "quality_assurance", "qa", "operations", "ops", "management"] },
  // Inventory & Quality overview (after /quality-control, which is narrower).
  { startsWith: "/quality", allowed: ["admin", "ops", "operations", "procurement", "finance", "sales", "quality_assurance", "qa", "management"] },
];

export const pathOf = (href: string) => href.split("?")[0].split("#")[0] || "/";

/** True when no restriction is set, or any of the roles is allowed. */
export function canView(roles: string[], allowed?: string[]): boolean {
  return !allowed || allowed.length === 0 || roles.some((r) => allowed.includes(r));
}

/** The roles the route guard allows on a path (undefined = any signed-in person). */
export function resolveRouteRoles(href: string): string[] | undefined {
  const path = pathOf(href);
  return ROUTE_ACCESS.find((r) => path.startsWith(r.startsWith))?.allowed;
}

/** Can these roles open this link - both the route guard and the menu entry (when it is one) let them through. */
export function canOpen(roles: string[], href: string): boolean {
  if (!canView(roles, resolveRouteRoles(href))) return false;
  const entry = findNavEntry(href);
  return !entry || canView(roles, entry.parent?.roles) && canView(roles, entry.roles);
}

type Found = { label: string; href: string; roles?: string[]; parent?: NavItem; icon: React.ElementType };

/** The menu entry for a link: exact (with its tab) first, then the same path. */
export function findNavEntry(href: string): Found | undefined {
  const all: Found[] = [];
  for (const item of NAV_ITEMS) {
    if (item.href) all.push({ label: item.label, href: item.href, roles: item.roles, icon: item.icon });
    for (const c of item.children ?? []) all.push({ label: c.label, href: c.href, roles: c.roles, parent: item, icon: item.icon });
  }
  return all.find((e) => e.href === href) ?? all.find((e) => pathOf(e.href) === pathOf(href) && !e.href.includes("?"))
    ?? all.find((e) => pathOf(e.href) === pathOf(href));
}

/** Where the page sits in the menu, e.g. "ACE Books > Invoice Register". */
export function menuPath(href: string): string | undefined {
  const e = findNavEntry(href);
  return e ? (e.parent ? `${e.parent.label} > ${e.label}` : e.label) : undefined;
}

/** Every page in the menu a set of roles can open, in menu order. */
export function visiblePages(roles: string[]): Found[] {
  const out: Found[] = [];
  for (const item of NAV_ITEMS) {
    if (!canView(roles, item.roles)) continue;
    if (item.href) out.push({ label: item.label, href: item.href, roles: item.roles, icon: item.icon });
    for (const c of (item.children ?? []) as NavChild[]) {
      if (canView(roles, c.roles)) out.push({ label: c.label, href: c.href, roles: c.roles, parent: item, icon: item.icon });
    }
  }
  return out;
}

/** Legacy role names fold into their main role (backend/src/roles.py). */
export const ROLE_ALIAS: Record<string, string> = { qa: "quality_assurance", operations: "ops", manager: "management" };
export const foldRole = (r: string) => ROLE_ALIAS[r] ?? r;

/** Most senior / broadest first: a person with several roles gets the broadest day. Never roles[0]. */
export const TOUR_ROLE_PRIORITY = ["admin", "management", "finance", "quality_assurance", "ops", "procurement",
                                   "sales", "frontdesk", "hr", "viewer"];

export function primaryTourRole(roles: string[] | null | undefined): string {
  const have = new Set((roles ?? []).map(foldRole));
  return TOUR_ROLE_PRIORITY.find((r) => have.has(r)) ?? "viewer";
}

/** A role plus its legacy alias, so a tour for "quality_assurance" is checked against menus that say "qa". */
export function withAliases(role: string): string[] {
  const out = new Set([role]);
  for (const [alias, main] of Object.entries(ROLE_ALIAS)) if (main === role) out.add(alias);
  return [...out];
}
