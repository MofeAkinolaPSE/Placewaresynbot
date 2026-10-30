/**
 * Builds a role's welcome tour: its day script (day-tours.ts) - or, for "Every page you can open", every menu page
 * that role can open with the page's own introduction (page-guides.ts). Both are filtered by the same access rules
 * as the menu and the route guard (nav-access.ts), so the tour never opens a page that would bounce the person.
 */
import { Compass } from "lucide-react";
import { getDayTour } from "./day-tours";
import { canOpen, findNavEntry, menuPath, visiblePages, withAliases } from "./nav-access";
import { getPageGuide } from "./walkthroughs";

export type TourStep = {
  label: string;
  href: string;
  description: string;
  icon: React.ElementType;
  points?: string[];
  /** Where it lives in the menu, so people learn their way round. */
  page?: string;
};

export function getTourStepsForRole(role: string, opts?: { full?: boolean }): TourStep[] {
  const roles = withAliases(role);
  if (!opts?.full) {
    const day = getDayTour(role);
    if (day?.length) {
      return day.filter((d) => canOpen(roles, d.href)).map((d) => ({
        label: d.title, href: d.href, description: d.body, points: d.points,
        page: menuPath(d.href) ?? (d.href === "/" ? "Dashboard" : undefined), icon: findNavEntry(d.href)?.icon ?? Compass,
      }));
    }
  }
  // every page in the menu this role can open, each with its introduction
  return visiblePages(roles).map((p) => {
    const g = getPageGuide(p.href);
    return { label: p.label, href: p.href, description: g?.intro ?? `${p.label}.`, page: menuPath(p.href), icon: p.icon };
  });
}

/** Roles offered in User Access's "Preview onboarding" (every role on ROLE_CATALOG). */
export const PREVIEW_ROLES: { value: string; label: string }[] = [
  { value: "frontdesk", label: "Frontdesk" },
  { value: "sales", label: "Sales" },
  { value: "finance", label: "Finance" },
  { value: "quality_assurance", label: "Quality assurance" },
  { value: "ops", label: "Operations" },
  { value: "procurement", label: "Procurement" },
  { value: "hr", label: "HR" },
  { value: "management", label: "Management" },
  { value: "admin", label: "Administrator" },
  { value: "viewer", label: "Viewer" },
];
