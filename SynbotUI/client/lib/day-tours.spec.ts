/** Welcome tour checks (guide section 11): every role has a day, and every step opens a page that role can open. */
import { readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";
import { DAY_ROLES, getDayTour } from "./day-tours";
import { getTourStepsForRole, PREVIEW_ROLES } from "./tour-config";
import { canOpen, pathOf, withAliases } from "./nav-access";

// backend/src/roles.py ROLE_CATALOG keys
const ROLE_CATALOG = ["frontdesk", "sales", "finance", "ops", "procurement", "quality_assurance", "hr", "management", "admin", "viewer"];
const APP = readFileSync(join(__dirname, "..", "App.tsx"), "utf8");
const ROUTES = [...APP.matchAll(/<Route path="([^"]+)"/g)].map((m) => m[1]);

describe("welcome tour", () => {
  it("every role on User Access has a day", () => {
    expect(ROLE_CATALOG.filter((r) => !DAY_ROLES.includes(r))).toEqual([]);
  });
  it("every role can be previewed", () => {
    expect(ROLE_CATALOG.filter((r) => !PREVIEW_ROLES.some((p) => p.value === r))).toEqual([]);
  });
  it("every step opens a real page the role can open", () => {
    const bad: string[] = [];
    for (const role of ROLE_CATALOG) {
      for (const s of getDayTour(role) ?? []) {
        if (!ROUTES.includes(pathOf(s.href))) bad.push(`${role}: ${s.href} is not a route`);
        else if (!canOpen(withAliases(role), s.href)) bad.push(`${role}: cannot open ${s.href}`);
      }
    }
    expect(bad).toEqual([]);
  });
  it("the tour is the day script, nothing dropped", () => {
    for (const role of ROLE_CATALOG) expect(getTourStepsForRole(role).length, role).toBe(getDayTour(role)!.length);
  });
  it("aliases get their main role's day", () => {
    expect(getDayTour("qa")).toBe(getDayTour("quality_assurance"));
    expect(getDayTour("operations")).toBe(getDayTour("ops"));
    expect(getDayTour("manager")).toBe(getDayTour("management"));
  });
  it("steps are real sentences", () => {
    for (const role of ROLE_CATALOG) for (const s of getDayTour(role)!) {
      expect(s.title.length, `${role}: ${s.title}`).toBeGreaterThan(5);
      expect(s.body.length, `${role}: ${s.title}`).toBeGreaterThan(30);
    }
  });
  it("every page tour covers what the role can open", () => {
    for (const role of ROLE_CATALOG) {
      const full = getTourStepsForRole(role, { full: true });
      expect(full.length, role).toBeGreaterThan(0);
      for (const s of full) expect(canOpen(withAliases(role), s.href), `${role}: ${s.href}`).toBe(true);
    }
  });
});
