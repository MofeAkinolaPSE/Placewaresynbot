import { useEffect } from "react";
import { useAuth } from "@/components/AuthProvider";
import { api } from "@/lib/api-client";

const HEARTBEAT_INTERVAL_MS = 30_000;

/**
 * Keeps this session's presence key alive for as long as the user has any
 * authenticated page open, regardless of which route they're on. Mounted
 * once in App.tsx as a sibling of SessionPrewarm, directly under
 * AuthProvider and above HashRouter -- the one spot in the tree that stays
 * mounted for the whole session instead of remounting on navigation.
 * Unlike SessionPrewarm this runs continuously, not once.
 */
export default function PresenceHeartbeat() {
  const { isAuthenticated, isLoading } = useAuth();

  useEffect(() => {
    if (isLoading || !isAuthenticated) return;

    const beat = () => {
      void api.presence.heartbeat().catch(() => {});
    };

    beat();
    const id = setInterval(beat, HEARTBEAT_INTERVAL_MS);
    return () => clearInterval(id);
  }, [isAuthenticated, isLoading]);

  return null;
}
