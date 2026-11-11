/**
 * Signs a person out when ACE has not been used for a while (client, 6 Nov): someone who walks away from
 * their desk does not leave their login - and their name on every invoice they "prepare" - open for
 * anyone else. A minute before, a pop-up asks "Still there?"; any key or click keeps the session.
 *
 * Activity in any ACE tab or window counts for all of them (kept in localStorage), so a printed invoice
 * open in a second tab does not sign the person out of the first. Default 30 minutes; a build can set
 * VITE_IDLE_SIGNOUT_MINUTES (0 turns it off).
 */
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const MINUTES = Number((import.meta as any).env?.VITE_IDLE_SIGNOUT_MINUTES ?? 30);
const IDLE_MS = MINUTES * 60_000;
const WARN_MS = 60_000;
const KEY = "ace:last-activity";
const EVENTS = ["mousemove", "mousedown", "keydown", "wheel", "touchstart", "scroll"] as const;

const lastActivity = () => Number(localStorage.getItem(KEY) || 0) || Date.now();

export function IdleSignOut() {
  const { isAuthenticated, logout } = useAuth();
  const [warning, setWarning] = useState(false);
  const [left, setLeft] = useState(60);
  const lastWrite = useRef(0);

  useEffect(() => {
    if (!isAuthenticated || !(IDLE_MS > 0)) return;
    const mark = () => {
      const now = Date.now();
      if (now - lastWrite.current < 5_000) return; // at most every 5 s
      lastWrite.current = now;
      localStorage.setItem(KEY, String(now));
    };
    lastWrite.current = 0;
    mark();
    EVENTS.forEach((e) => window.addEventListener(e, mark, { passive: true }));
    const tick = setInterval(() => {
      const idle = Date.now() - lastActivity();
      if (idle >= IDLE_MS) {
        clearInterval(tick);
        setWarning(false);
        localStorage.removeItem(KEY);
        void logout();
      } else if (idle >= IDLE_MS - WARN_MS) {
        setLeft(Math.max(0, Math.ceil((IDLE_MS - idle) / 1000)));
        setWarning(true);
      } else {
        setWarning(false);
      }
    }, 1_000);
    return () => {
      clearInterval(tick);
      EVENTS.forEach((e) => window.removeEventListener(e, mark));
    };
  }, [isAuthenticated, logout]);

  if (!isAuthenticated || !warning) return null;
  const stay = () => { lastWrite.current = Date.now(); localStorage.setItem(KEY, String(Date.now())); setWarning(false); };
  return (
    <Dialog open onOpenChange={(o) => { if (!o) stay(); }}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Still there?</DialogTitle>
          <DialogDescription>
            ACE hasn't been used for {MINUTES} minutes. You'll be signed out in <strong>{left}s</strong> so nobody else can work under your name.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => { localStorage.removeItem(KEY); void logout(); }}>Sign out now</Button>
          <Button onClick={stay}>Stay signed in</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
