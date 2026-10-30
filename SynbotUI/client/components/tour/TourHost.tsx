import { useEffect, useRef, type ReactNode } from "react";
import { useAuth } from "@/components/AuthProvider";
import { api } from "@/lib/api-client";
import { primaryTourRole } from "@/lib/nav-access";
import { TourProvider, useTour } from "./TourProvider";
import { WalkthroughProvider } from "./WalkthroughProvider";

/** Starts the welcome tour on a person's first sign-in - every account, however it was created (guide 4.3, 13). */
function FirstRunTour() {
  const { isAuthenticated, roles } = useAuth();
  const { startTourIfNeeded } = useTour();
  const asked = useRef(false);
  useEffect(() => {
    if (!isAuthenticated || !roles.length || asked.current) return;
    asked.current = true;
    api.staff.getTourState()
      .then((r) => startTourIfNeeded(primaryTourRole(roles), r?.tour_state))
      .catch(() => {});
  }, [isAuthenticated, roles, startTourIfNeeded]);
  return null;
}

/** Welcome tour + Show me how, around every signed-in page (mounted by Layout, inside the router). */
export function TourHost({ children }: { children: ReactNode }) {
  return (
    <TourProvider>
      <WalkthroughProvider>
        <FirstRunTour />
        {children}
      </WalkthroughProvider>
    </TourProvider>
  );
}
