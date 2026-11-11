/**
 * "Notify me on this device" - next to the bell. Turns phone / desktop notifications on or off for this
 * device, and sends a test. People who approve invoices (Finance, management, admin) are offered it once
 * with a small banner, so the CFO/CEO get "invoice waiting for your approval" on their phone.
 */
import { useEffect, useState } from "react";
import { BellRing, Smartphone, X } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/components/AuthProvider";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api-client";
import { PushState, pushState, relinkPush, turnPushOff, turnPushOn } from "@/lib/push";

const APPROVERS = ["finance", "management", "admin"];
const OFFER_KEY = "ace:push-offer-dismissed";

function usePush() {
  const { isAuthenticated } = useAuth();
  const [state, setState] = useState<PushState | null>(null);
  useEffect(() => {
    if (!isAuthenticated) return;
    void relinkPush();
    void pushState().then(setState);
  }, [isAuthenticated]);
  const on = async () => {
    try {
      const s = await turnPushOn();
      setState(s);
      if (s === "on") toast.success("Notifications are on for this device", { description: "You'll be told here when something needs your approval." });
      else if (s === "blocked") toast.error("Notifications are blocked for ACE", { description: "Allow them in the browser's site settings, then try again." });
    } catch (e: any) {
      toast.error("Couldn't turn notifications on", { description: e?.message });
    }
  };
  const off = async () => setState(await turnPushOff());
  return { state, on, off };
}

const HELP: Record<PushState, string> = {
  on: "This device is told when something needs you - an invoice waiting for approval, an escalation - even with ACE closed.",
  off: "Get a notification on this device when something needs you, such as an invoice waiting for your approval.",
  blocked: "Notifications are blocked for ACE in this browser. Allow them in the site settings (the padlock by the address), then come back here.",
  "needs-install": "On an iPhone: tap Share, then Add to Home Screen, open ACE from the Home Screen and turn notifications on there (iOS 16.4 or later).",
  unsupported: "This browser can't show notifications from ACE. Use Chrome, Edge or Safari, on the secure (https) address.",
};

export function PushNotificationsButton() {
  const { state, on, off } = usePush();
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  if (!state) return null;
  const run = async (f: () => Promise<void>) => { setBusy(true); try { await f(); } finally { setBusy(false); } };
  return (
    <div className="relative">
        <button type="button" title="Notifications on this device" aria-label="Notifications on this device" onClick={() => setOpen((v) => !v)}
                className="relative flex h-7 w-7 items-center justify-center rounded-md border border-border/40 bg-muted/30 hover:bg-muted/60">
          <Smartphone className="h-3.5 w-3.5" />
          {state === "on" && <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-success" />}
        </button>
      {open && (<>
      <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
      <div className="absolute right-0 z-40 mt-1 w-72 space-y-2 rounded-lg border bg-card p-3 text-sm shadow-lg">
        <div className="flex items-center gap-2 font-semibold"><BellRing className="h-4 w-4" />Notifications on this device</div>
        <p className="text-xs text-muted-foreground">{HELP[state]}</p>
        {state === "on" ? (
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={busy} onClick={() => run(async () => {
              const r = await api.push.test();
              if (r.sent) toast.success("Test sent", { description: "It should appear on this device in a few seconds." });
              else toast.error("The test didn't go through", { description: "Turn notifications off and on again on this device." });
            })}>Send a test</Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(off)}>Turn off</Button>
          </div>
        ) : state === "off" ? (
          <Button size="sm" disabled={busy} onClick={() => run(on)}>Notify me on this device</Button>
        ) : null}
      </div>
      </>)}
    </div>
  );
}

/** One-time offer for the people who approve invoices. */
export function PushOffer() {
  const { roles } = useAuth();
  const { state, on } = usePush();
  const [hidden, setHidden] = useState(() => localStorage.getItem(OFFER_KEY) === "1");
  if (hidden || state !== "off" || !roles.some((r) => APPROVERS.includes(r))) return null;
  const dismiss = () => { localStorage.setItem(OFFER_KEY, "1"); setHidden(true); };
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-sky-300 bg-sky-50 px-3 py-2 text-sm text-sky-900 dark:bg-sky-500/10 dark:text-sky-200">
      <BellRing className="h-4 w-4 shrink-0" />
      <span className="flex-1">Get a notification on this device when an invoice is waiting for your approval - even when ACE is closed.</span>
      <Button size="sm" onClick={async () => { await on(); dismiss(); }}>Turn on</Button>
      <button type="button" aria-label="Not now" className="rounded p-1 hover:bg-sky-100 dark:hover:bg-sky-500/20" onClick={dismiss}><X className="h-4 w-4" /></button>
    </div>
  );
}
