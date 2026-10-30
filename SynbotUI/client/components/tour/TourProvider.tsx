import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Compass, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getTourStepsForRole, type TourStep } from "@/lib/tour-config";
import { api } from "@/lib/api-client";
import { TourStepContent } from "./TourStep";

type TourState = { completed?: boolean; skipped?: boolean; current_step?: number };

type TourContextValue = {
  /** First sign-in: does nothing once the person has finished or skipped it. */
  startTourIfNeeded: (role: string, tourState: TourState | null | undefined) => void;
  /** Replay (user menu, Show me how, User Access preview): starts at step 1 and never writes progress. */
  startTour: (role: string, opts?: { full?: boolean }) => void;
  hasTour: (role: string) => boolean;
};

const TourContext = createContext<TourContextValue | null>(null);

export function useTour() {
  const ctx = useContext(TourContext);
  if (!ctx) throw new Error("useTour must be used within a TourProvider");
  return ctx;
}

/**
 * The welcome tour (guide 4.3, 10): a floating card, bottom right, not a modal - each step opens its page behind the
 * card so the person sees the real screen. First run resumes where they left off and records progress; a replay
 * writes nothing.
 */
export function TourProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [steps, setSteps] = useState<TourStep[]>([]);
  const [stepIndex, setStepIndex] = useState(0);
  const [open, setOpen] = useState(false);
  const [isReplay, setIsReplay] = useState(false);
  const [full, setFull] = useState(false);

  const persist = useCallback((patch: TourState) => { void api.staff.updateTourState(patch).catch(() => {}); }, []);

  const startTourIfNeeded = useCallback((role: string, tourState: TourState | null | undefined) => {
    if (tourState?.completed || tourState?.skipped) return;
    const s = getTourStepsForRole(role);
    if (!s.length) return;
    setIsReplay(false); setFull(false); setSteps(s);
    setStepIndex(Math.min(tourState?.current_step ?? 0, s.length - 1));
    setOpen(true);
  }, []);

  const startTour = useCallback((role: string, opts?: { full?: boolean }) => {
    const s = getTourStepsForRole(role, opts);
    if (!s.length) return;
    setIsReplay(true); setFull(!!opts?.full); setSteps(s); setStepIndex(0); setOpen(true);
  }, []);

  const hasTour = useCallback((role: string) => getTourStepsForRole(role).length > 0, []);

  const finish = useCallback(() => {
    setOpen(false);
    if (!isReplay) persist({ completed: true, current_step: steps.length });
  }, [persist, steps.length, isReplay]);
  const skip = useCallback(() => { setOpen(false); if (!isReplay) persist({ skipped: true }); }, [persist, isReplay]);
  const next = useCallback(() => {
    if (stepIndex + 1 >= steps.length) { finish(); return; }
    if (!isReplay) persist({ current_step: stepIndex + 1 });
    setStepIndex(stepIndex + 1);
  }, [stepIndex, steps.length, finish, persist, isReplay]);
  const back = useCallback(() => setStepIndex((i) => Math.max(0, i - 1)), []);

  const value = useMemo(() => ({ startTourIfNeeded, startTour, hasTour }), [startTourIfNeeded, startTour, hasTour]);
  const current = steps[stepIndex];

  useEffect(() => {
    if (!open || !current) return;
    if (location.pathname + location.search !== current.href) navigate(current.href);
  }, [open, stepIndex, current?.href]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <TourContext.Provider value={value}>
      {children}
      {open && current && (
        <div data-tour-ui role="dialog" aria-modal="false" aria-label={isReplay ? "Guided tour" : "Welcome tour"}
             className="fixed bottom-4 right-4 z-[100] w-[min(440px,calc(100vw-2rem))] rounded-xl border bg-card p-5 text-card-foreground shadow-2xl">
          <div className="mb-3 flex items-center justify-between gap-2">
            <p className="flex items-center gap-2 text-sm font-semibold">
              <Compass className="h-4 w-4 text-primary" />
              {full ? "Every page you can open" : isReplay ? "Your day in ACE" : "Welcome to ACE - here is your day"}
            </p>
            <button type="button" aria-label="Close the tour" className="rounded p-1 text-muted-foreground hover:bg-muted" onClick={skip}><X className="h-4 w-4" /></button>
          </div>
          <div className="max-h-[55vh] overflow-y-auto pr-1">
            <TourStepContent step={current} index={stepIndex} total={steps.length} />
          </div>
          <div className="mt-4 flex items-center justify-between gap-2 border-t pt-3">
            <Button variant="ghost" size="sm" onClick={skip}>{isReplay ? "Close" : "Skip tour"}</Button>
            <div className="flex items-center gap-2">
              {stepIndex > 0 && <Button variant="outline" size="sm" onClick={back}>Back</Button>}
              <Button size="sm" onClick={next}>{stepIndex + 1 >= steps.length ? "Finish" : "Next"}</Button>
            </div>
          </div>
        </div>
      )}
    </TourContext.Provider>
  );
}
