import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/components/AuthProvider";
import { api } from "@/lib/api-client";

const PREWARM_STALE_TIME_MS = 120_000;

export default function SessionPrewarm() {
  const queryClient = useQueryClient();
  const { isAuthenticated, isLoading } = useAuth();
  const warmedRef = useRef(false);

  useEffect(() => {
    if (isLoading || !isAuthenticated || warmedRef.current) {
      if (!isAuthenticated) {
        warmedRef.current = false;
      }
      return;
    }

    warmedRef.current = true;

    const prewarm = async () => {
      await Promise.allSettled([
        queryClient.prefetchQuery({
          queryKey: ["dashboard-revenue"],
          queryFn: () => api.dashboard.finance(),
          staleTime: PREWARM_STALE_TIME_MS,
        }),
        queryClient.prefetchQuery({
          queryKey: ["dashboard-alerts"],
          queryFn: () => api.dashboard.alerts(),
          staleTime: PREWARM_STALE_TIME_MS,
        }),
        queryClient.prefetchQuery({
          queryKey: ["dashboard-stock"],
          queryFn: () => api.inventory.stock(),
          staleTime: PREWARM_STALE_TIME_MS,
        }),
        queryClient.prefetchQuery({
          queryKey: ["dashboard-workforce"],
          queryFn: () => api.dashboard.workforce(),
          staleTime: PREWARM_STALE_TIME_MS,
        }),
        queryClient.prefetchQuery({
          queryKey: ["executive-briefing"],
          queryFn: () => api.dashboard.briefing(),
          staleTime: PREWARM_STALE_TIME_MS,
        }),
        queryClient.prefetchQuery({
          queryKey: ["executive-summary"],
          queryFn: () => api.intelligence.executiveSummary(),
          staleTime: PREWARM_STALE_TIME_MS,
        }),
        queryClient.prefetchQuery({
          queryKey: ["finance-kpis"],
          queryFn: () => api.dashboard.finance(),
          staleTime: PREWARM_STALE_TIME_MS,
        }),
        queryClient.prefetchQuery({
          queryKey: ["finance-trend"],
          queryFn: () => api.finance.trend(),
          staleTime: PREWARM_STALE_TIME_MS,
        }),
        queryClient.prefetchQuery({
          queryKey: ["ops-kpis"],
          queryFn: () => api.ops.kpis(),
          staleTime: PREWARM_STALE_TIME_MS,
        }),
        queryClient.prefetchQuery({
          queryKey: ["workflow-pending"],
          queryFn: () => api.workflow.pending(),
          staleTime: PREWARM_STALE_TIME_MS,
        }),
      ]);
    };

    void prewarm();
  }, [isAuthenticated, isLoading, queryClient]);

  return null;
}
