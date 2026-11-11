/**
 * Live updates across the app: when Frontdesk, Finance or ACE Books changes an invoice, a receipt, stock or a
 * visit, every open screen that shows it refreshes by itself - no page reload (client, 28 Oct and 6 Nov:
 * "the finance team had to refresh before the invoice popped up"). One listener for the whole app: it
 * marks only the affected data stale, and only screens on show fetch again.
 *
 * - frontdesk_updates: an invoice raised, changed, approved, posted, voided, dispatched.
 * - books_updates: any save in ACE Books (posting, receipt, void, payment, adjustment).
 * - inventory_updates: stock movements.
 * After a dropped connection comes back everything shown is refreshed (events sent meanwhile were missed),
 * and while a channel is down the waiting-for-Finance lists are re-read every 30 s so nothing is stuck.
 */
import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/components/AuthProvider";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";

const FRONTDESK_KEYS = [["fd-invoices"], ["fd-daily-report"], ["fd-invoice-detail"], ["invoice-history"], ["quality"], ["customer-360"],
  ["customer-workspace"], ["books"], ["workstation"], ["ws", "inbox"]]; // the bell: a voided invoice leaves it at once
const BOOKS_KEYS = [["books"], ["fd-invoices"], ["fd-invoice-detail"], ["customer-360"], ["customer-workspace"], ["inventory"], ["workstation"]];
const INVENTORY_KEYS = [["quality"], ["books"], ["inventory"]];
// what someone may be waiting on: polled only while live updates are down
const FALLBACK_KEYS = [["fd-invoices"], ["books"], ["ws", "inbox"]];

// "subscriber_joined" is the server's hello to a new socket - nothing changed
const IGNORED = new Set(["subscriber_joined", "pong"]);

export function LiveUpdates() {
  const { isAuthenticated } = useAuth();
  const qc = useQueryClient();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pending = useRef<unknown[][]>([]);
  const refresh = (keys: unknown[][]) => {
    pending.current.push(...keys);
    if (timer.current) clearTimeout(timer.current);
    // a burst of events (approval, then its posting) refreshes once
    timer.current = setTimeout(() => {
      const seen = new Set<string>();
      for (const k of pending.current.splice(0)) {
        const id = JSON.stringify(k);
        if (seen.has(id)) continue;
        seen.add(id);
        qc.invalidateQueries({ queryKey: k });
      }
    }, 300);
  };
  const on = (keys: unknown[][]) => (msg: any) => { if (!IGNORED.has(msg?.event)) refresh(keys); };

  const fdLive = useRealtimeChannel("frontdesk_updates", on(FRONTDESK_KEYS), isAuthenticated);
  const booksLive = useRealtimeChannel("books_updates", on(BOOKS_KEYS), isAuthenticated);
  useRealtimeChannel("inventory_updates", on(INVENTORY_KEYS), isAuthenticated);

  const down = isAuthenticated && !(fdLive && booksLive);
  useEffect(() => {
    if (!down) return;
    const t = setInterval(() => {
      if (document.visibilityState === "visible") refresh(FALLBACK_KEYS);
    }, 30_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [down]);

  return null;
}
