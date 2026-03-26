import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

function extractQuotedValues(source: string, pattern: RegExp): string[] {
  const values: string[] = [];
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(source)) !== null) {
    if (match[1]) values.push(match[1]);
  }
  return values;
}

describe("navigation guardrail", () => {
  it("detects orphan app routes and missing sidebar route references", () => {
    const appPath = path.resolve(__dirname, "../App.tsx");
    const sidebarPath = path.resolve(__dirname, "../components/Sidebar.tsx");

    const appSource = fs.readFileSync(appPath, "utf8");
    const sidebarSource = fs.readFileSync(sidebarPath, "utf8");

    const appRoutes = new Set(
      extractQuotedValues(appSource, /<Route\s+path="([^"]+)"/g).filter((route) => route && route !== "*")
    );
    const sidebarRoutes = new Set(extractQuotedValues(sidebarSource, /href:\s*"([^"]+)"/g));

    const excludedFromSidebar = new Set([
      "/login",
      "/executive/summary",       // drilldown from Executive page, not a direct nav item
      "/finance/reports/ar/:bucket", // parameterised detail route
    ]);

    const appRoutesForSidebar = [...appRoutes].filter(
      (route) => !excludedFromSidebar.has(route) && !route.includes(":")
    );

    const sidebarMissingInApp = [...sidebarRoutes].filter((route) => !appRoutes.has(route));
    const orphanAppRoutes = appRoutesForSidebar.filter((route) => !sidebarRoutes.has(route));

    expect(
      sidebarMissingInApp,
      `Sidebar references routes not present in App router: ${sidebarMissingInApp.join(", ")}`,
    ).toEqual([]);

    expect(
      orphanAppRoutes,
      `App routes missing sidebar references (potential orphan pages): ${orphanAppRoutes.join(", ")}`,
    ).toEqual([]);
  });
});
