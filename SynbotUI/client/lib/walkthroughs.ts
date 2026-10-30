/**
 * "Show me how" - on-demand walkthroughs over the live ACE pages (docs/ACE-Guided-Onboarding-Engineering-Guide.md).
 *
 * Two kinds, both played by components/tour/WalkthroughPlayer.tsx:
 *  - Page guides (lib/tour/page-guides.ts): one per page, every tab and every button on it, in screen order.
 *  - Journeys (lib/tour/journeys.ts): one record (an order, a batch, a recall) through the departments it crosses.
 *
 * A step points at a control either by `anchor` (a data-tour-id on the element) or by `target` - the control's own
 * on-screen label (a tab, button or link with that text). A missing control degrades to a plain explanation.
 *
 * Safety (guide section 7): most actions post to ACE Books at once and every screen updates live for everyone, so
 * anything that saves, posts, approves, voids or sends is `caution` - shown, explained, never pressed. Only tabs,
 * searches, filters, opening a panel and Print are `click` steps. Checked by walkthroughs.spec.ts.
 *
 * Ask ACE's APP_GUIDE (backend/src/services/app_guide.py), the welcome tour (day-tours.ts) and these walkthroughs
 * describe the same flows with the same button names: change one, change the other two.
 */
import { JOURNEYS } from "./tour/journeys";
import { PAGE_GUIDES } from "./tour/page-guides";
import { canOpen, foldRole, pathOf, resolveRouteRoles, withAliases } from "./nav-access";

export type TargetKind = "tab" | "button" | "link" | "field" | "row" | "any";

export type WalkthroughStep = {
  title: string;
  body: string;
  /** data-tour-id of the element to highlight. */
  anchor?: string;
  /** Or: the control's visible label, e.g. "Invoice register". Matched exactly, then as the start of the label. */
  target?: string;
  /** What kind of control `target` names (default: any clickable). "row": the first clickable row of the list on
   *  screen (or the one containing `target`) - for "open any invoice" steps. */
  kind?: TargetKind;
  /** Route to open before this step (journeys cross pages; a page guide opens its tab this way). */
  navigateTo?: string;
  /** click: safe to press, the step advances when pressed. observe (default): look only. */
  action?: "click" | "observe";
  /** Commits something (posts, approves, voids, saves, sends): amber, never clickable. */
  caution?: boolean;
  /** Short instruction under the body. */
  cue?: string;
};

export type Walkthrough = {
  id: string;
  title: string;
  /** One line, shown in the Show me how menu. */
  summary: string;
  /** Offered to these roles (aliases folded). Undefined = whoever can open the page. */
  roles?: string[];
  /** The page it starts on; Show me how lists it first there. */
  homeRoute: string;
  estMinutes: number;
  kind: "page" | "journey";
  steps: WalkthroughStep[];
};

export type PageGuide = {
  route: string;
  /** Page name as in the menu. */
  title: string;
  /** One or two sentences: what the page is for. Also the welcome tour's text for this page. */
  intro: string;
  steps: WalkthroughStep[];
};

const minutes = (n: number) => Math.max(1, Math.round(n * 0.4));

/** A page guide as a walkthrough: an opening step that names the page, then its tabs and buttons. */
function pageWalkthrough(g: PageGuide): Walkthrough {
  return {
    id: `page:${g.route}`,
    title: `Tour of this page: ${g.title}`,
    summary: `Every tab and button on ${g.title}, what it does and when to use it.`,
    homeRoute: g.route,
    estMinutes: minutes(g.steps.length + 1),
    kind: "page",
    steps: [{ title: `${g.title}: what this page is for`, body: g.intro, navigateTo: g.route }, ...g.steps],
  };
}

export const PAGE_WALKTHROUGHS: Walkthrough[] = PAGE_GUIDES.map(pageWalkthrough);
export const ALL_WALKTHROUGHS: Walkthrough[] = [...JOURNEYS, ...PAGE_WALKTHROUGHS];

/** May any of these roles use this walkthrough: listed for it (if it lists roles) and able to open its page. */
export function availableTo(w: Walkthrough, roles: string[]): boolean {
  const all = roles.flatMap((r) => withAliases(foldRole(r)));
  if (w.roles && !w.roles.some((r) => all.includes(r))) return false;
  return canOpen(all, w.homeRoute);
}

export function getWalkthroughsForRoles(roles: string[]): Walkthrough[] {
  return ALL_WALKTHROUGHS.filter((w) => availableTo(w, roles));
}

export function getWalkthroughsForRole(role: string): Walkthrough[] {
  return getWalkthroughsForRoles([role]);
}

/** What Show me how offers on a page: this page's guide first, then journeys that start here, then the rest. */
export function getWalkthroughsForRoute(route: string, roles: string[]): { here: Walkthrough[]; elsewhere: Walkthrough[] } {
  const path = pathOf(route);
  const mine = getWalkthroughsForRoles(roles);
  const isHere = (w: Walkthrough) => pathOf(w.homeRoute) === path;
  const here = [...mine.filter((w) => isHere(w) && w.kind === "page"), ...mine.filter((w) => isHere(w) && w.kind === "journey")];
  return { here, elsewhere: mine.filter((w) => !isHere(w)) };
}

export function getWalkthroughById(id: string): Walkthrough | undefined {
  return ALL_WALKTHROUGHS.find((w) => w.id === id);
}

/** The page a step is on: its own navigateTo, else the last one before it, else where the walkthrough starts. */
export function pageOfStep(w: Walkthrough, i: number): string {
  for (let k = i; k >= 0; k--) if (w.steps[k]?.navigateTo) return w.steps[k].navigateTo!;
  return w.homeRoute;
}

/** Step i as a given person sees it. A step on a page their roles cannot open is told, not shown: the player does
 *  not navigate there (the route guard would bounce them) and says whose page it is instead. */
export function stepFor(w: Walkthrough, i: number, roles: string[]): (WalkthroughStep & { elsewhere?: string }) | undefined {
  const step = w.steps[i];
  if (!step) return undefined;
  const page = pageOfStep(w, i);
  const all = roles.flatMap((r) => withAliases(foldRole(r)));
  if (canOpen(all, page)) return step;
  const owners = (resolveRouteRoles(page) ?? []).filter((r) => !["admin", "qa", "operations", "manager", "crm"].includes(r));
  const who = owners.length ? owners.map((r) => r.replace(/_/g, " ")).join(", ") : "another team";
  return { title: step.title, body: step.body, caution: step.caution, elsewhere: `This part happens on a page for ${who} - shown here so you know what happens next.` };
}

export function getPageGuide(route: string): PageGuide | undefined {
  return PAGE_GUIDES.find((g) => g.route === route) ?? PAGE_GUIDES.find((g) => pathOf(g.route) === pathOf(route));
}

export { resolveRouteRoles };
