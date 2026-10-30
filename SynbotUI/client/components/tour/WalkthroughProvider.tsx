import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { getWalkthroughById, type Walkthrough } from "@/lib/walkthroughs";
import { WalkthroughPlayer } from "./WalkthroughPlayer";

/**
 * The running Show me how walkthrough, held above the pages (in Layout) so a journey that moves from Frontdesk to
 * ACE Books keeps going when the page that started it unmounts, and so it can be minimised and resumed.
 */
type WalkthroughState = { walkthrough: Walkthrough; step: number; minimised: boolean };

type Ctx = {
  active: WalkthroughState | null;
  start: (id: string) => void;
  goToStep: (n: number) => void;
  minimise: () => void;
  resume: () => void;
  stop: () => void;
};

const WalkthroughCtx = createContext<Ctx | null>(null);

export function useWalkthrough(): Ctx {
  const ctx = useContext(WalkthroughCtx);
  if (!ctx) throw new Error("useWalkthrough must be used inside WalkthroughProvider");
  return ctx;
}

export function WalkthroughProvider({ children }: { children: React.ReactNode }) {
  const [active, setActive] = useState<WalkthroughState | null>(null);
  const start = useCallback((id: string) => {
    const w = getWalkthroughById(id);
    if (w) setActive({ walkthrough: w, step: 0, minimised: false });
  }, []);
  const goToStep = useCallback((n: number) => {
    setActive((s) => (s ? { ...s, step: Math.max(0, Math.min(n, s.walkthrough.steps.length - 1)), minimised: false } : s));
  }, []);
  const minimise = useCallback(() => setActive((s) => (s ? { ...s, minimised: true } : s)), []);
  const resume = useCallback(() => setActive((s) => (s ? { ...s, minimised: false } : s)), []);
  const stop = useCallback(() => setActive(null), []);
  const value = useMemo(() => ({ active, start, goToStep, minimise, resume, stop }), [active, start, goToStep, minimise, resume, stop]);
  return (
    <WalkthroughCtx.Provider value={value}>
      {children}
      {active && <WalkthroughPlayer />}
    </WalkthroughCtx.Provider>
  );
}
