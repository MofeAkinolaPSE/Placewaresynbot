import { useState } from "react";
import { Eye, GraduationCap, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getTourStepsForRole, PREVIEW_ROLES } from "@/lib/tour-config";
import { getWalkthroughsForRole } from "@/lib/walkthroughs";
import { menuPath } from "@/lib/nav-access";
import { useTour } from "./TourProvider";
import { useWalkthrough } from "./WalkthroughProvider";

/**
 * User Access → Preview onboarding (guide 4.6): play any role's welcome tour, or any walkthrough it is offered,
 * without creating a test login. Runs as a replay, so nothing is recorded for anyone.
 */
export function TourPreview() {
  const { startTour } = useTour();
  const { start } = useWalkthrough();
  const [role, setRole] = useState("frontdesk");
  const [showAll, setShowAll] = useState(false);
  const day = getTourStepsForRole(role);
  const pages = getTourStepsForRole(role, { full: true });
  const walks = getWalkthroughsForRole(role);
  const journeys = walks.filter((w) => w.kind === "journey");
  const pageTours = walks.filter((w) => w.kind === "page");
  const label = PREVIEW_ROLES.find((r) => r.value === role)?.label ?? role;

  return (
    <div className="pw-surface-interactive space-y-4 rounded-xl p-6" data-tour-label="Preview onboarding">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><GraduationCap className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold text-foreground">Preview onboarding</h2>
          <p className="mt-1 text-sm text-muted-foreground">See what a new person in a role meets on their first sign-in, and the Show me how walkthroughs they are offered - without creating a test login. Nothing is recorded.</p>
        </div>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1 text-sm">
          <span className="block text-xs font-medium text-muted-foreground">Role</span>
          <select className="h-10 rounded-md border bg-background px-3 text-sm" value={role} onChange={(e) => { setRole(e.target.value); setShowAll(false); }} aria-label="Preview role">
            {PREVIEW_ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </label>
        <Button onClick={() => startTour(role)}><Play className="mr-2 h-4 w-4" />Play {label} welcome tour ({day.length} steps)</Button>
        <Button variant="outline" onClick={() => startTour(role, { full: true })}><Eye className="mr-2 h-4 w-4" />Every page they can open ({pages.length})</Button>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Their day ({day.length} steps)</h3>
          <ol className="space-y-1 text-sm">
            {day.map((s, i) => <li key={i} className="flex gap-2"><span className="w-5 shrink-0 text-right text-muted-foreground">{i + 1}.</span><span>{s.label}<span className="text-xs text-muted-foreground"> · {s.page ?? s.href}</span></span></li>)}
          </ol>
        </div>
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Show me how: {journeys.length} journeys, {pageTours.length} page tours</h3>
          <ul className="space-y-1 text-sm">
            {[...journeys, ...(showAll ? pageTours : pageTours.slice(0, 6))].map((w) => (
              <li key={w.id} className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate">{w.title}<span className="text-xs text-muted-foreground"> · {menuPath(w.homeRoute) ?? w.homeRoute}</span></span>
                <Button size="sm" variant="ghost" className="h-7 shrink-0 px-2" onClick={() => start(w.id)}><Play className="h-3.5 w-3.5" /></Button>
              </li>
            ))}
          </ul>
          {pageTours.length > 6 && <Button size="sm" variant="link" className="px-0" onClick={() => setShowAll((v) => !v)}>{showAll ? "Show fewer" : `Show all ${pageTours.length} page tours`}</Button>}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">A walkthrough plays on the pages as you can open them: steps on pages that role cannot open are explained to them, not shown.</p>
    </div>
  );
}
