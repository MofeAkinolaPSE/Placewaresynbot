import Sidebar from "./Sidebar";
import FloatingChat from "./FloatingChat";
import { Outlet } from "react-router-dom";
import { getSynbotConfig } from "@/lib/wp-config";
import { Button } from "@/components/ui/button";
import { useAuth } from "./AuthProvider";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Menu } from "lucide-react";

const Layout = () => {
  const { logout } = useAuth();
  const queryClient = useQueryClient();
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { role, apiBaseUrl, wpUserId } = getSynbotConfig();
  const hasRole = typeof role === "string" && role.trim().length > 0;
  const hasApiBase = typeof apiBaseUrl === "string" && apiBaseUrl.trim().length > 0;

  const handleSignOut = async () => {
    if (isSigningOut) return;
    setIsSigningOut(true);
    try {
      await logout();
      queryClient.clear();
    } finally {
      setIsSigningOut(false);
    }
  };

  return (
    <div className="pw-page-surface flex">
      <Sidebar mobileOpen={mobileNavOpen} onMobileClose={() => setMobileNavOpen(false)} />
      <main className="relative z-10 min-h-screen flex-1 bg-transparent lg:ml-64">
        <div className="pw-surface-interactive mx-4 mt-4 flex items-center justify-between px-4 py-3 text-xs text-muted-foreground sm:mx-6 sm:px-6">
          <div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mb-2 lg:hidden"
              onClick={() => setMobileNavOpen(true)}
            >
              <Menu className="mr-2 h-4 w-4" />
              Menu
            </Button>
            <span className="font-semibold text-foreground">PlacewareBot Admin Session</span>
            <span className="mx-2">·</span>
            <span>
              Role: {hasRole ? role : "unavailable"}
            </span>
            {typeof wpUserId === "number" && (
              <span className="ml-2">(WP User ID: {wpUserId})</span>
            )}
            {!hasRole && <span className="ml-2 text-destructive">(runtime role missing)</span>}
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden rounded-xl border border-border/50 bg-muted/30 px-3 py-1.5 sm:block">
              <span>
                API: {hasApiBase ? apiBaseUrl : "missing"}
              </span>
              {!hasApiBase && (
                <span className="ml-2 text-destructive">(runtime API base missing)</span>
              )}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleSignOut}
              disabled={isSigningOut}
            >
              {isSigningOut ? "Signing out..." : "Sign out"}
            </Button>
          </div>
        </div>
        <div className="relative z-10 px-3 pb-8 pt-6 sm:px-6">
          <Outlet />
        </div>
      </main>
      <FloatingChat />
    </div>
  );
};

export default Layout;
