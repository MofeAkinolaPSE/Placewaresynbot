import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/components/AuthProvider";
import { api } from "@/lib/api-client";

const PREWARM_STALE_TIME_MS = 120_000;
const has = (roles: string[], allowed: string[]) => roles.some((r) => allowed.includes(r));

/**
 * Warms what this person will actually open, by role - so nobody triggers requests they are
 * not allowed to make (those came back 403 on every page load) and the retired AI executive
 * briefing, which nothing shows any more, is no longer generated on every login.
 */
export default function SessionPrewarm() {
  const queryClient = useQueryClient();
  const { isAuthenticated, isLoading, roles } = useAuth();
  const warmedRef = useRef(false);

  useEffect(() => {
    if (isLoading || !isAuthenticated || warmedRef.current) {
      if (!isAuthenticated) {
        warmedRef.current = false;
      }
      return;
    }

    warmedRef.current = true;
    const warm = (queryKey: unknown[], queryFn: () => Promise<unknown>) =>
      queryClient.prefetchQuery({ queryKey, queryFn, staleTime: PREWARM_STALE_TIME_MS });

    const jobs: Promise<unknown>[] = [warm(["ws", "day"], () => api.workspace.day())];
    if (has(roles, ["admin", "management", "finance"])) {
      jobs.push(warm(["executive-overview"], () => api.dashboard.executive()));
    }
    if (has(roles, ["admin", "management", "finance", "ops"])) {
      // the general Dashboard page (backend require_management)
      jobs.push(
        warm(["dashboard-revenue"], () => api.dashboard.finance()),
        warm(["dashboard-alerts"], () => api.dashboard.alerts()),
        warm(["finance-kpis"], () => api.dashboard.finance()),
      );
    }
    if (has(roles, ["admin", "management", "finance", "ops", "hr"])) {
      jobs.push(warm(["dashboard-workforce"], () => api.dashboard.workforce()));
    }
    void Promise.allSettled(jobs);
  }, [isAuthenticated, isLoading, queryClient, roles]);

  return null;
}
