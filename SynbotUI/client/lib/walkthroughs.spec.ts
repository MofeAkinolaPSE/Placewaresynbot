/**
 * Show me how checks (docs/ACE-Guided-Onboarding-Engineering-Guide.md section 11): every page has a guide, every
 * anchor exists, every route is real, nothing that posts is clickable, and nobody is sent to a page they cannot open.
 */
import { readdirSync, readFileSync, statSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";
import { ALL_WALKTHROUGHS, PAGE_WALKTHROUGHS, availableTo, getWalkthroughsForRole, getWalkthroughsForRoute, pageOfStep, stepFor } from "./walkthroughs";
import { PAGE_GUIDES } from "./tour/page-guides";
import { JOURNEYS } from "./tour/journeys";
import { canOpen, pathOf, primaryTourRole, withAliases } from "./nav-access";

const CLIENT = join(__dirname, "..");
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) return f === "node_modules" ? [] : sources(p);
    return /\.tsx?$/.test(f) && !f.endsWith(".spec.ts") ? [p] : [];
  });
}
const ALL_SRC = sources(CLIENT).map((p) => readFileSync(p, "utf8")).join("\n");
const APP = readFileSync(join(CLIENT, "App.tsx"), "utf8");
const ROUTES = [...APP.matchAll(/<Route path="([^"]+)"/g)].map((m) => m[1]);
const PAGE_ROUTES = [...APP.matchAll(/<Route path="([^"]+)" element=\{(?!<Navigate)/g)].map((m) => m[1])
  .filter((r) => !r.includes(":") && r !== "*" && !["/login", "/rider"].includes(r));
const ROLES = ["frontdesk", "sales", "finance", "ops", "procurement", "quality_assurance", "hr", "management", "admin", "viewer"];

describe("page guides", () => {
  it("every page in App.tsx has a guide", () => {
    const covered = new Set(PAGE_GUIDES.map((g) => g.route));
    expect(PAGE_ROUTES.filter((r) => !covered.has(r))).toEqual([]);
  });
  it("every guide is for a real route", () => {
    expect(PAGE_GUIDES.map((g) => g.route).filter((r) => !ROUTES.includes(r))).toEqual([]);
  });
  it("every guide explains its page and has steps", () => {
    for (const g of PAGE_GUIDES) {
      expect(g.intro.length, g.route).toBeGreaterThan(40);
      expect(g.steps.length, g.route).toBeGreaterThan(1);
    }
  });
  it("one guide per route", () => {
    const routes = PAGE_GUIDES.map((g) => g.route);
    expect(routes.length).toBe(new Set(routes).size);
  });
});

describe("walkthrough steps", () => {
  const steps = ALL_WALKTHROUGHS.flatMap((w) => w.steps.map((s) => ({ w, s })));
  it("titles and bodies are real sentences", () => {
    expect(steps.filter(({ s }) => s.title.length <= 3 || s.body.length <= 25).map(({ w, s }) => `${w.id}: ${s.title} - "${s.body}"`)).toEqual([]);
  });
  it("a caution step is never a click step", () => {
    expect(steps.filter(({ s }) => s.caution && s.action === "click").map(({ w, s }) => `${w.id}: ${s.title}`)).toEqual([]);
  });
  it("a click step points at something", () => {
    expect(steps.filter(({ s }) => s.action === "click" && !s.anchor && !s.target && s.kind !== "row").map(({ w, s }) => `${w.id}: ${s.title}`)).toEqual([]);
  });
  it("committing controls are always caution", () => {
    const committing = /^(void|void invoice|approve|pass qc|fail qc|post bill|record the bill|create user|delete|deactivate|edit access|back up now|save|save settings|confirm arrived|release|reject|initiate recall|complete recall|new delivery|send for delivery|pay supplier|supplier bill|journal entry|adjustment|lend stock|year-end close|register & proceed to invoice|message customers|invoice|record receipt|credit note|register asset|new account)$/i;
    const bad = steps.filter(({ s }) => s.target && committing.test(s.target) && !s.caution
      // opening a form is fine to explain without the amber card when the step says so (see-only, never clicked)
      && s.action === "click");
    expect(bad.map(({ w, s }) => `${w.id}: ${s.target}`)).toEqual([]);
  });
  it("every anchor exists in the code as data-tour-id", () => {
    const anchors = [...new Set(steps.map(({ s }) => s.anchor).filter(Boolean) as string[])];
    // written as data-tour-id="x", or as tourId: "x" on a list the page renders into data-tour-id
    expect(anchors.filter((a) => !ALL_SRC.includes(`data-tour-id="${a}"`) && !ALL_SRC.includes(`tourId: "${a}"`))).toEqual([]);
  });
  it("every navigateTo is a real route", () => {
    const bad = steps.filter(({ s }) => s.navigateTo && !ROUTES.includes(pathOf(s.navigateTo))).map(({ w, s }) => `${w.id}: ${s.navigateTo}`);
    expect(bad).toEqual([]);
  });
  it("nobody is sent to a page they cannot open", () => {
    const bad: string[] = [];
    for (const w of ALL_WALKTHROUGHS) {
      for (const role of ROLES) {
        if (!availableTo(w, [role])) continue;
        if (!canOpen(withAliases(role), w.homeRoute)) bad.push(`${w.id} as ${role}: starts on ${w.homeRoute}`);
        // a step elsewhere is told, never navigated to (stepFor)
        w.steps.forEach((_, k) => {
          const s = stepFor(w, k, [role])!;
          if (s.navigateTo && !canOpen(withAliases(role), s.navigateTo)) bad.push(`${w.id} as ${role}: ${s.navigateTo}`);
          if ((s.target || s.anchor) && !canOpen(withAliases(role), pageOfStep(w, k))) bad.push(`${w.id} as ${role}: points at ${s.target ?? s.anchor} on ${pageOfStep(w, k)}`);
        });
      }
    }
    expect(bad).toEqual([]);
  });
  it("a step on someone else's page says whose it is", () => {
    const w = JOURNEYS.find((j) => j.id === "qc-batch-release")!;
    const k = w.steps.findIndex((x) => x.navigateTo === "/finance/books/purchases");
    const s = stepFor(w, k, ["quality_assurance"])!;
    expect(s.navigateTo).toBeUndefined();
    expect(s.target).toBeUndefined();
    expect(s.elsewhere).toContain("finance");
  });
  it("every journey has something to do, not just read", () => {
    for (const w of JOURNEYS) expect(w.steps.some((s) => s.action === "click"), w.id).toBe(true);
  });
  it("journeys keep the rules people must not forget", () => {
    const text = JOURNEYS.flatMap((w) => w.steps.map((s) => s.body)).join(" ").toLowerCase();
    for (const phrase of ["the person who raised an invoice cannot qc it", "posts to ace books", "40800", "49000", "quarantined"]) {
      expect(text, phrase).toContain(phrase);
    }
    const qc = PAGE_GUIDES.find((g) => g.route === "/quality-control")!.steps.map((s) => s.body).join(" ").toLowerCase();
    expect(qc).toContain("expired lots can never be sold");
  });
});

describe("who sees what", () => {
  it("every role has walkthroughs, and only for pages it can open", () => {
    for (const role of ROLES) {
      const mine = getWalkthroughsForRole(role);
      expect(mine.length, role).toBeGreaterThan(0);
      for (const w of mine) expect(canOpen(withAliases(role), w.homeRoute), `${role}: ${w.id}`).toBe(true);
    }
  });
  it("the page guide comes first on its own page", () => {
    const { here } = getWalkthroughsForRoute("/frontdesk", ["frontdesk"]);
    expect(here[0].id).toBe("page:/frontdesk");
    expect(here.map((w) => w.id)).toContain("frontdesk-walkin");
  });
  it("a frontdesk person is not offered ACE Books tours", () => {
    expect(getWalkthroughsForRole("frontdesk").some((w) => w.homeRoute.startsWith("/finance/books"))).toBe(false);
  });
  it("legacy role names get the same walkthroughs", () => {
    expect(getWalkthroughsForRoles_(["qa"])).toEqual(getWalkthroughsForRoles_(["quality_assurance"]));
  });
  it("multi-role and alias accounts get the right tour", () => {
    expect(primaryTourRole(["frontdesk", "management"])).toBe("management");
    expect(primaryTourRole(["qa"])).toBe("quality_assurance");
    expect(primaryTourRole(["operations"])).toBe("ops");
    expect(primaryTourRole([])).toBe("viewer");
  });
  it("every page guide is a walkthrough", () => {
    expect(PAGE_WALKTHROUGHS.length).toBe(PAGE_GUIDES.length);
  });
});

function getWalkthroughsForRoles_(roles: string[]) {
  return ALL_WALKTHROUGHS.filter((w) => availableTo(w, roles)).map((w) => w.id);
}
