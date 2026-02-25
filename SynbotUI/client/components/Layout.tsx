import Sidebar from "./Sidebar";
import { Outlet } from "react-router-dom";
import { getSynbotConfig } from "@/lib/wp-config";
import { Button } from "@/components/ui/button";
import { useAuth } from "./AuthProvider";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

const Layout = () => {
  const { logout } = useAuth();
  const queryClient = useQueryClient();
  const [isSigningOut, setIsSigningOut] = useState(false);
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
    <div className="flex">
      <Sidebar />
      <main className="ml-64 flex-1 min-h-screen bg-background">
        <div className="border-b border-border bg-card px-6 py-2 text-xs text-muted-foreground flex items-center justify-between">
          <div>
            <span className="font-semibold">Synbot Admin Session</span>
            <span className="mx-2">·</span>
            <span>
              Role: {hasRole ? role : "unavailable"}
            </span>
            {typeof wpUserId === "number" && (
              <span className="ml-2">(WP User ID: {wpUserId})</span>
            )}
            {!hasRole && (
              <span className="ml-2 text-destructive">(runtime role missing)</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden sm:block">
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
        <Outlet />
      </main>
    </div>
  );
};

export default Layout;
