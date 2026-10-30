/**
 * Live updates across the app (client, 28 Oct): when Frontdesk, QC, Finance or ACE Books changes an invoice or
 * a visit, every open screen that shows it refreshes by itself - no page reload. One listener for the whole app
 * (instead of every page polling, which the capacity work turned off): it marks only the affected data stale.
 */
import { useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/components/AuthProvider";
import { useRealtimeChannel } from "@/hooks/use-realtime-channel";

const FRONTDESK_KEYS = [["fd-invoices"], ["fd-daily-report"], ["fd-invoice-detail"], ["invoice-history"], ["quality"], ["customer-360"],
  ["customer-workspace"], ["books"], ["workstation"]];

export function LiveUpdates() {
  const { isAuthenticated } = useAuth();
  const qc = useQueryClient();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refresh = (keys: unknown[][]) => {
    if (timer.current) clearTimeout(timer.current);
    // a burst of events (QC pass, then finance approval) refreshes once
    timer.current = setTimeout(() => keys.forEach((k) => qc.invalidateQueries({ queryKey: k })), 300);
  };
  useRealtimeChannel("frontdesk_updates", () => refresh(FRONTDESK_KEYS), isAuthenticated);
  useRealtimeChannel("inventory_updates", () => refresh([["quality"], ["books"], ["inventory"]]), isAuthenticated);
  return null;
}
