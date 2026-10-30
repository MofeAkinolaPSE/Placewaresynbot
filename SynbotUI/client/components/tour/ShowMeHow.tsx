import { useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { Compass, GraduationCap, Map, Route, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useAuth } from "@/components/AuthProvider";
import { getWalkthroughsForRoute, type Walkthrough } from "@/lib/walkthroughs";
import { menuPath, primaryTourRole } from "@/lib/nav-access";
import { cn } from "@/lib/utils";
import { useWalkthrough } from "./WalkthroughProvider";
import { useTour } from "./TourProvider";

/**
 * "Show me how" - in the top bar of every page (guide 4.5). Opens a panel: this page's tour (every tab and
 * button on it) and the journeys that start here first, then every other walkthrough the person's roles may use,
 * searchable, plus the welcome tour again. Only what their roles can open is offered.
 */
export function ShowMeHow({ className }: { className?: string }) {
  const { roles } = useAuth();
  const location = useLocation();
  const { start } = useWalkthrough();
  const { startTour } = useTour();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const mine = roles?.length ? roles : ["viewer"];
  const { here, elsewhere } = useMemo(() => getWalkthroughsForRoute(location.pathname, mine), [location.pathname, mine.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const t = q.trim().toLowerCase();
  const match = (w: Walkthrough) => !t || `${w.title} ${w.summary} ${menuPath(w.homeRoute) ?? ""}`.toLowerCase().includes(t);
  const journeys = elsewhere.filter((w) => w.kind === "journey" && match(w));
  const pages = elsewhere.filter((w) => w.kind === "page" && match(w));
  const go = (w: Walkthrough) => { setOpen(false); setQ(""); start(w.id); };

  const Item = ({ w }: { w: Walkthrough }) => (
    <button type="button" onClick={() => go(w)}
            className="flex w-full items-start gap-3 rounded-lg border bg-card px-3 py-2 text-left hover:border-primary/50 hover:bg-primary/5">
      {w.kind === "page" ? <Map className="mt-0.5 h-4 w-4 shrink-0 text-primary" /> : <Route className="mt-0.5 h-4 w-4 shrink-0 text-primary" />}
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium leading-snug">{w.title}</span>
        <span className="block text-xs text-muted-foreground">{w.summary}</span>
        <span className="block text-[11px] text-muted-foreground">{menuPath(w.homeRoute) ?? w.homeRoute} · {w.steps.length} steps · about {w.estMinutes} min</span>
      </span>
    </button>
  );

  return (
    <>
      <button type="button" data-tour-id="show-me-how" onClick={() => setOpen(true)} title="Show me how: guided walkthroughs of this page and your work"
              className={cn("flex h-7 items-center gap-1.5 rounded-md border border-primary/40 bg-primary/10 px-2 text-xs font-medium text-primary hover:bg-primary/15", className)}>
        <GraduationCap className="h-3.5 w-3.5" /><span className="hidden sm:inline">Show me how</span>
      </button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="right" className="flex w-full flex-col gap-3 sm:max-w-md">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2"><GraduationCap className="h-5 w-5 text-primary" />Show me how</SheetTitle>
            <SheetDescription>
              A guide plays over the real page and lights up each tab and button in turn. Safe clicks only: anything that saves or posts is shown, never pressed.
            </SheetDescription>
          </SheetHeader>
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input className="pl-8" placeholder="Search, e.g. receipt, void, batch, recall" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search walkthroughs" />
          </div>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
            {here.filter(match).length > 0 && (
              <section className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">On this page</h3>
                {here.filter(match).map((w) => <Item key={w.id} w={w} />)}
              </section>
            )}
            {journeys.length > 0 && (
              <section className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Follow the work, start to finish</h3>
                {journeys.map((w) => <Item key={w.id} w={w} />)}
              </section>
            )}
            {pages.length > 0 && (
              <section className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Tour of any page</h3>
                {pages.map((w) => <Item key={w.id} w={w} />)}
              </section>
            )}
            {!here.filter(match).length && !journeys.length && !pages.length && (
              <p className="text-sm text-muted-foreground">Nothing matches "{q}". Try another word, or ask ACE (the chat button, bottom right).</p>
            )}
          </div>
          <Button variant="outline" onClick={() => { setOpen(false); startTour(primaryTourRole(mine)); }}>
            <Compass className="mr-2 h-4 w-4" />Take the welcome tour again
          </Button>
        </SheetContent>
      </Sheet>
    </>
  );
}
