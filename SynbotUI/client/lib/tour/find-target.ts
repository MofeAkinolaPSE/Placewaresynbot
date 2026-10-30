/**
 * Finds the control a walkthrough step points at on the live page: by data-tour-id, or by its on-screen label.
 * Searches open dialogs/sheets first (a panel on top is what the person is looking at), then the page itself;
 * the side menu and the top bar are left out so "Invoice Register" finds the tab, not the menu link (in-page bars
 * such as ACE Books' section bar are <nav> elements too, so the side menu is marked rather than every nav skipped).
 */
import type { TargetKind } from "../walkthroughs";

const SELECTOR: Record<TargetKind, string> = {
  tab: "[role=tab]",
  button: "button, [role=button], a[role=button]",
  link: "a[href]",
  field: "input, select, textarea, label, [role=combobox]",
  row: "tbody tr, [data-tour-row]",
  any: "[role=tab], button, [role=button], a[href], [role=menuitem], [role=option], summary, label, h1, h2, h3, h4, [data-tour-label]",
};

export const norm = (s: string | null | undefined) =>
  (s ?? "").replace(/[……]/g, "").replace(/\s+/g, " ").trim().toLowerCase();

function labelOf(el: HTMLElement): string {
  return norm(el.getAttribute("data-tour-label") || el.getAttribute("aria-label") || el.innerText || el.getAttribute("title")
    || (el as HTMLInputElement).placeholder || "");
}

function visible(el: HTMLElement): boolean {
  const r = el.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return false;
  const st = getComputedStyle(el);
  return st.visibility !== "hidden" && st.display !== "none";
}

function roots(): HTMLElement[] {
  const dialogs = [...document.querySelectorAll<HTMLElement>("[role=dialog], [role=alertdialog]")]
    .filter((d) => visible(d) && !d.closest("[data-tour-ui]"));
  const main = document.querySelector<HTMLElement>("main");
  return [...dialogs.reverse(), ...(main ? [main] : [document.body])];
}

export function findTarget(step: { anchor?: string; target?: string; kind?: TargetKind }): HTMLElement | null {
  if (step.anchor) {
    const all = [...document.querySelectorAll<HTMLElement>(`[data-tour-id="${step.anchor}"]`)].filter(visible);
    if (all.length) return all[0];
  }
  if (step.kind === "row") {
    // "click any row": the first clickable row of the list on screen (optionally the one containing `target`)
    for (const root of roots()) {
      const rows = [...root.querySelectorAll<HTMLElement>(SELECTOR.row)]
        .filter((e) => !e.closest("[data-tour-ui]") && visible(e) && (getComputedStyle(e).cursor === "pointer" || !!e.querySelector("button, a[href]")));
      const hit = step.target ? rows.find((r) => labelOf(r).includes(norm(step.target))) : rows[0];
      if (hit) return hit;
    }
    return null;
  }
  if (!step.target) return null;
  const want = norm(step.target);
  const sel = SELECTOR[step.kind ?? "any"];
  for (const root of roots()) {
    const els = [...root.querySelectorAll<HTMLElement>(sel)]
      .filter((e) => !e.closest("[data-tour-ui]") && !e.closest("[data-tour-sidebar]") && !e.closest("[data-tour-topbar]") && visible(e));
    const exact = els.find((e) => labelOf(e) === want);
    if (exact) return exact;
    const starts = els.find((e) => labelOf(e).startsWith(want));
    if (starts) return starts;
    // a label that contains the text (e.g. an icon button "+ Invoice"), short labels only
    const contains = els.find((e) => { const l = labelOf(e); return l.length <= want.length + 24 && l.includes(want); });
    if (contains) return contains;
  }
  return null;
}
