import Sidebar from "./Sidebar";
import FloatingChat from "./FloatingChat";
import { Outlet } from "react-router-dom";
import { getSynbotConfig } from "@/lib/wp-config";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import { Menu, Circle } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

const Layout = () => {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [onlineListOpen, setOnlineListOpen] = useState(false);
  const { role, apiBaseUrl, wpUserId } = getSynbotConfig();
  const hasRole = typeof role === "string" && role.trim().length > 0;
  const hasApiBase = typeof apiBaseUrl === "string" && apiBaseUrl.trim().length > 0;

  // Global "who's online" -- shown on every page via this persistent top
  // bar, not just the HR dashboard, per the "always aware of who's online"
  // ask. Deliberately not department-scoped. PresenceHeartbeat.tsx (mounted
  // in App.tsx) is what keeps this session's own presence key alive.
  const { data: presenceData } = useQuery({
    queryKey: ["presence-online"],
    queryFn: () => api.presence.online(),
    refetchInterval: 30_000,
  });
  const onlineUsers = presenceData?.users ?? [];

  return (
    <div className="pw-page-surface flex">
      <Sidebar mobileOpen={mobileNavOpen} onMobileClose={() => setMobileNavOpen(false)} />
      <main className="relative z-10 min-h-screen flex-1 bg-transparent lg:ml-64">
        {/* Slim diagnostic top bar */}
        <div className="pw-surface-interactive mx-4 mt-4 flex items-center justify-between px-4 py-2.5 text-xs text-muted-foreground sm:mx-6 sm:px-6">
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mr-1 lg:hidden"
              onClick={() => setMobileNavOpen(true)}
            >
              <Menu className="mr-2 h-4 w-4" />
              Menu
            </Button>
            <span className="font-semibold text-foreground">ACE</span>
            <span className="opacity-40">·</span>
            <span>Role: {hasRole ? role : <span className="text-destructive">unavailable</span>}</span>
            {typeof wpUserId === "number" && (
              <span className="opacity-50">(WP User: {wpUserId})</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <button
                type="button"
                onClick={() => setOnlineListOpen((v) => !v)}
                className="flex items-center gap-1.5 rounded-lg border border-border/40 bg-muted/30 px-2.5 py-1 hover:bg-muted/60 transition-colors"
              >
                <Circle className="h-2 w-2 fill-success text-success" />
                {onlineUsers.length} online
              </button>
              {onlineListOpen && (
                <>
                  <div className="fixed inset-0 z-30" onClick={() => setOnlineListOpen(false)} />
                  <div className="absolute right-0 z-40 mt-1 w-56 rounded-lg border bg-card shadow-lg overflow-hidden">
                    <div className="px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground border-b">
                      Currently Online
                    </div>
                    {onlineUsers.length === 0 ? (
                      <div className="px-3 py-3 text-xs text-muted-foreground">No one else is online right now.</div>
                    ) : (
                      <ul className="max-h-64 overflow-y-auto">
                        {onlineUsers.map((u) => (
                          <li key={u.user_id} className="px-3 py-2 border-b last:border-0 text-xs">
                            <div className="font-medium text-foreground">{u.email?.split("@")[0] || u.user_id}</div>
                            <div className="text-muted-foreground">{(u.roles || []).join(", ") || "—"}</div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </>
              )}
            </div>
            <div className="hidden items-center gap-2 sm:flex">
              <div className="rounded-lg border border-border/40 bg-muted/30 px-2.5 py-1">
                API: {hasApiBase ? apiBaseUrl : <span className="text-destructive">missing</span>}
              </div>
            </div>
          </div>
        </div>
        {/* Page content */}
        <div className="relative z-10 px-3 pb-8 pt-5 sm:px-6">
          <Outlet />
        </div>
      </main>
      <FloatingChat />
    </div>
  );
};

export default Layout;
