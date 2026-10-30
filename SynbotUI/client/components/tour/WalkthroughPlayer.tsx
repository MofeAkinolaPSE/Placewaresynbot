import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import { AlertTriangle, ArrowDown, ArrowUp, Check, ChevronLeft, ChevronRight, Eye, GraduationCap, List, Minus, MousePointerClick, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { findTarget } from "@/lib/tour/find-target";
import { useWalkthrough } from "./WalkthroughProvider";
import { useAuth } from "@/components/AuthProvider";
import { stepFor } from "@/lib/walkthroughs";

type Rect = { top: number; left: number; width: number; height: number };
const PAD = 8;
const CARD_W = 420;
const GAP = 16;

/**
 * Plays a Show me how walkthrough over the live ACE page (guide section 10).
 *
 * The spotlight is four dimmed panels drawn AROUND the control, all pointer-events:none: nothing covers the
 * control, so it stays readable and clickable, and the rest of the page keeps working. "click" steps advance when
 * the person presses the real control; "caution" steps (anything that posts, approves, voids, saves or sends) are
 * amber and say "Look, do not press" - colleagues see every posting live, so training never acts.
 * The pulse stays in place (no scaling "ping": on wide ACE tables that drew a giant box off the target).
 */
export function WalkthroughPlayer() {
  const navigate = useNavigate();
  const location = useLocation();
  const { active, goToStep, minimise, resume, stop } = useWalkthrough();
  const [rect, setRect] = useState<Rect | null>(null);
  const [showSteps, setShowSteps] = useState(false);
  const [nudge, setNudge] = useState(0);
  const lastNavigated = useRef<string | null>(null);
  // An open panel (invoice, bill, batch…) is a modal: a press on this card would count as "outside" and close it,
  // taking the controls the next steps point at with it. The card keeps its presses and focus to itself.
  const cardRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = cardRef.current;
    if (!el) return;
    const keep = (e: Event) => e.stopPropagation();
    el.addEventListener("pointerdown", keep);
    el.addEventListener("mousedown", keep);
    el.addEventListener("focusin", keep);
    return () => { el.removeEventListener("pointerdown", keep); el.removeEventListener("mousedown", keep); el.removeEventListener("focusin", keep); };
  });

  const { roles } = useAuth();
  const walkthrough = active?.walkthrough;
  const i = active?.step ?? 0;
  // a step on a page this person cannot open is explained, not navigated to (stepFor)
  const step = useMemo(() => (walkthrough ? stepFor(walkthrough, i, roles) : undefined), [walkthrough, i, roles]);
  const isLast = walkthrough ? i === walkthrough.steps.length - 1 : false;
  const pointsAt = !!(step?.anchor || step?.target || step?.kind === "row");
  const wantsClick = step?.action === "click" && pointsAt && !step.caution;

  const next = useCallback(() => {
    if (!walkthrough) return;
    if (i >= walkthrough.steps.length - 1) stop();
    else goToStep(i + 1);
  }, [walkthrough, i, goToStep, stop]);

  // Open the step's page once per step; never fight someone who has since moved on deliberately.
  useEffect(() => {
    if (!step?.navigateTo) { lastNavigated.current = null; return; }
    const key = `${walkthrough?.id}:${i}:${step.navigateTo}`;
    if (lastNavigated.current === key) return;
    lastNavigated.current = key;
    if (location.pathname + location.search !== step.navigateTo) navigate(step.navigateTo);
  }, [step, i, walkthrough?.id, navigate]); // eslint-disable-line react-hooks/exhaustive-deps

  // Measure after paint and keep tracking: the control moves when the page scrolls, a tab opens or data loads.
  useLayoutEffect(() => {
    if (!active || active.minimised) return;
    let settled = false;
    const measure = (scroll = false) => {
      const el = findTarget(step ?? {});
      if (!el) { setRect(null); return; }
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) { setRect(null); return; }
      setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
      if (scroll && !settled) {
        settled = true;
        if (r.top < 90 || r.bottom > window.innerHeight - 90) el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    };
    const raf = requestAnimationFrame(() => measure(true));
    const retries = [250, 600, 1100, 2000].map((ms) => setTimeout(() => measure(true), ms));
    const track = () => measure(false);
    window.addEventListener("resize", track);
    window.addEventListener("scroll", track, true);
    const poll = setInterval(track, 400);
    return () => {
      cancelAnimationFrame(raf); retries.forEach(clearTimeout); clearInterval(poll);
      window.removeEventListener("resize", track); window.removeEventListener("scroll", track, true);
    };
  }, [step, active]);

  // Learn by doing: a click step completes when the real control is pressed (found again at the moment of the
  // click, since React may have re-rendered it).
  useEffect(() => {
    if (!wantsClick || !active || active.minimised) return;
    const onClick = (e: MouseEvent) => {
      const el = findTarget(step ?? {});
      if (el && e.target instanceof Node && el.contains(e.target)) setTimeout(next, 300);
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [wantsClick, step, active, next]);

  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
      if (e.key === "Escape") { if (active.minimised) stop(); else minimise(); }
      else if (!typing && e.key === "ArrowRight") next();
      else if (!typing && e.key === "ArrowLeft") goToStep(i - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, i, next, goToStep, minimise, stop]);

  if (!active || !walkthrough || !step) return null;

  if (active.minimised) {
    return createPortal(
      <div data-tour-ui className="fixed bottom-20 right-4 z-[120] flex items-center gap-2 rounded-full border bg-background/95 py-1.5 pl-3 pr-1.5 shadow-lg backdrop-blur">
        <GraduationCap className="h-4 w-4 text-primary" />
        <div className="text-xs"><span className="font-medium">{walkthrough.title}</span>
          <span className="ml-1.5 text-muted-foreground">{i + 1}/{walkthrough.steps.length}</span></div>
        <Button size="sm" className="h-6 px-2 text-xs" onClick={resume}>Resume</Button>
        <button onClick={stop} aria-label="End walkthrough" className="rounded-full p-1 text-muted-foreground hover:bg-muted hover:text-foreground"><X className="h-3.5 w-3.5" /></button>
      </div>,
      document.body,
    );
  }

  const spot = rect ? { top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 } : null;
  const ring = step.caution ? "rgb(245 158 11)" : "hsl(var(--primary))";
  let cardStyle: React.CSSProperties;
  let arrow: "up" | "down" | null = null;
  if (spot) {
    const left = Math.max(GAP, Math.min(spot.left, window.innerWidth - CARD_W - GAP));
    const below = spot.top + spot.height + GAP;
    if (window.innerHeight - below > 300) { cardStyle = { top: below, left }; arrow = "up"; }
    else if (spot.top > 320) { cardStyle = { bottom: window.innerHeight - spot.top + GAP, left }; arrow = "down"; }
    else { cardStyle = { bottom: GAP, right: GAP }; }
  } else {
    cardStyle = { top: "50%", left: "50%", transform: "translate(-50%, -50%)" };
  }
  const dim = "pointer-events-none absolute bg-slate-950/50 transition-all duration-300 ease-out";

  return createPortal(
    <div data-tour-ui className="pointer-events-none fixed inset-0 z-[110]">
      {spot ? (
        <>
          <div className={dim} style={{ top: 0, left: 0, right: 0, height: Math.max(0, spot.top) }} />
          <div className={dim} style={{ top: spot.top + spot.height, left: 0, right: 0, bottom: 0 }} />
          <div className={dim} style={{ top: spot.top, left: 0, width: Math.max(0, spot.left), height: spot.height }} />
          <div className={dim} style={{ top: spot.top, left: spot.left + spot.width, right: 0, height: spot.height }} />
          <div key={`${i}-${nudge}`} className="pointer-events-none absolute rounded-lg transition-all duration-300 ease-out"
               style={{ ...spot, boxShadow: `0 0 0 3px ${ring}, 0 0 0 8px ${ring}33, 0 0 28px 6px ${ring}55` }} />
          <div key={`pulse-${i}-${nudge}`} className="pointer-events-none absolute rounded-lg motion-safe:animate-pulse"
               style={{ ...spot, animationDuration: "1.8s", boxShadow: `0 0 0 6px ${ring}55` }} />
        </>
      ) : (
        <div className="pointer-events-none absolute inset-0 bg-slate-950/30" />
      )}

      <div ref={cardRef} role="dialog" aria-modal="false" aria-label={`Show me how: ${walkthrough.title}`} style={cardStyle}
           className={cn("pointer-events-auto absolute w-[min(420px,calc(100vw-2rem))] overflow-hidden rounded-xl border bg-background text-foreground shadow-2xl",
                         step.caution && "border-amber-500/60")}>
        <div className="h-1 w-full bg-muted">
          <div className={cn("h-full transition-all duration-300", step.caution ? "bg-amber-500" : "bg-primary")}
               style={{ width: `${((i + 1) / walkthrough.steps.length) * 100}%` }} />
        </div>
        <div className="p-4">
          <div className="mb-2 flex items-start gap-2.5">
            <div className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", step.caution ? "bg-amber-500/15 text-amber-600" : "bg-primary/10 text-primary")}>
              {arrow === "up" ? <ArrowUp className="h-4 w-4" /> : arrow === "down" ? <ArrowDown className="h-4 w-4" /> : <GraduationCap className="h-4 w-4" />}
            </div>
            <div className="min-w-0 flex-1">
              <button onClick={() => setShowSteps((v) => !v)} title="Show all steps"
                      className="flex w-full min-w-0 items-center gap-1.5 text-left text-xs text-muted-foreground hover:text-foreground">
                <List className="h-3 w-3 shrink-0" /><span className="truncate">{walkthrough.title}</span>
                <span className="shrink-0">· step {i + 1} of {walkthrough.steps.length}</span>
              </button>
              <p className="mt-0.5 text-base font-semibold leading-snug">{step.title}</p>
            </div>
            <div className="flex shrink-0 items-center gap-0.5">
              <button onClick={minimise} aria-label="Minimise walkthrough" title="Minimise - keeps your place" className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"><Minus className="h-4 w-4" /></button>
              <button onClick={stop} aria-label="End walkthrough" className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"><X className="h-4 w-4" /></button>
            </div>
          </div>

          {showSteps && (
            <div className="mb-3 max-h-56 overflow-y-auto rounded-lg border bg-muted/40 p-1">
              {walkthrough.steps.map((s, n) => (
                <button key={n} onClick={() => { goToStep(n); setShowSteps(false); }}
                        className={cn("flex w-full items-start gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-background", n === i && "bg-background font-medium")}>
                  <span className={cn("mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px]",
                                      n < i ? "bg-primary/15 text-primary" : n === i ? "bg-primary text-primary-foreground" : "bg-muted-foreground/20 text-muted-foreground")}>
                    {n < i ? <Check className="h-2.5 w-2.5" /> : n + 1}
                  </span>
                  <span className="min-w-0 flex-1 leading-snug">{s.title}</span>
                </button>
              ))}
            </div>
          )}

          <div className="max-h-[38vh] overflow-y-auto">
            <p className="text-sm leading-relaxed text-foreground/85">{step.body}</p>
          </div>

          {wantsClick && (
            <button onClick={() => { setNudge((n) => n + 1); findTarget(step)?.scrollIntoView({ behavior: "smooth", block: "center" }); }}
                    className="mt-3 flex w-full items-center gap-2 rounded-lg border border-primary/40 bg-primary/10 px-3 py-2 text-left text-xs font-medium text-primary hover:bg-primary/15">
              <MousePointerClick className="h-4 w-4 shrink-0 motion-safe:animate-pulse" />
              <span className="flex-1">{step.cue ?? `Click ${step.target ? `"${step.target}"` : "the highlighted control"} to continue`}</span>
              <span className="text-xs font-normal opacity-70">show me</span>
            </button>
          )}
          {step.caution && (
            <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span><strong>Look, do not press.</strong> {step.cue ?? "This saves or posts for real, and colleagues see it at once."}</span>
            </div>
          )}
          {!wantsClick && !step.caution && step.cue && (
            <div className="mt-3 flex items-start gap-2 rounded-lg border bg-muted/50 px-3 py-2 text-xs">
              <Eye className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" /><span>{step.cue}</span>
            </div>
          )}
          {step.elsewhere && (
            <div className="mt-3 flex items-start gap-2 rounded-lg border bg-muted/50 px-3 py-2 text-xs"><Eye className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" /><span>{step.elsewhere}</span></div>
          )}
          {!rect && pointsAt && (
            <p className="mt-2 text-xs italic text-muted-foreground">
              That control is not on screen right now - it lives {step.target ? `under "${step.target}" ` : ""}on a tab, panel or form that is not open. Open it and it will light up, or press Next.
            </p>
          )}

          <div className="mt-4 flex items-center justify-between gap-3 border-t pt-3">
            <p className="min-w-0 flex-1 text-xs leading-snug text-muted-foreground">You are on the real page: safe clicks only - nothing is saved unless you save it.</p>
            <div className="flex shrink-0 items-center gap-1.5">
              {i > 0 && <Button variant="outline" size="sm" className="h-7 px-2" onClick={() => goToStep(i - 1)} aria-label="Previous step"><ChevronLeft className="h-3.5 w-3.5" /></Button>}
              <Button size="sm" className="h-7" variant={wantsClick ? "outline" : "default"} onClick={next}>
                {isLast ? "Done" : wantsClick ? "Skip" : "Next"}{!isLast && <ChevronRight className="ml-1 h-3.5 w-3.5" />}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
