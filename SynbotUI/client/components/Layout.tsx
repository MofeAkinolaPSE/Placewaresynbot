import Sidebar from "./Sidebar";
import FloatingChat from "./FloatingChat";
import { Link, Outlet } from "react-router-dom";
import { ClockPill } from "./staff/ws-kit";
import { API_BASE_URL } from "@/lib/api-base";
import { useAuth } from "./AuthProvider";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import { Menu, Circle, ArrowLeft, ArrowRight, Bell } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import ThemeToggle from "./ThemeToggle";
import { useBackForward } from "@/hooks/use-back-forward";

const Layout = () => {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [onlineListOpen, setOnlineListOpen] = useState(false);
  // Role comes from the signed-in user's token (same source as the Sidebar),
  // never from getSynbotConfig(): that falls back to localStorage
  // "synbot_config", which is shared by every app ever served on this origin
  // (https://localhost) and showed a stale "doctor" role from another build.
  const { roles } = useAuth();
  const roleLabel = roles.map((r) => r.replace(/_/g, " ")).join(", ");

  // In-app Back/Forward -- on every page via this shared Layout, so it
  // works the same regardless of whether you got here via the sidebar, a
  // quick-action button, or another Back click. Going back always returns
  // you to exactly where you were, including scroll/selection state React
  // Router preserves on its own.
  const { goBack, goForward, canGoBack, canGoForward } = useBackForward();

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
  // unread workspace notifications (requests, mentions, assignments) for the bell
  const { data: inboxData } = useQuery({
    queryKey: ["ws", "inbox", "all"],
    queryFn: () => api.workspace.inbox("all"),
    refetchInterval: 60_000,
  });
  const unread = inboxData?.counts?.unread ?? 0;

  return (
    <div className="pw-page-surface pw-safe-top flex w-full overflow-x-hidden">
      <Sidebar mobileOpen={mobileNavOpen} onMobileClose={() => setMobileNavOpen(false)} />
      <main className="relative z-10 min-h-dvh w-full min-w-0 flex-1 bg-transparent lg:ml-64">
        {/* Slim diagnostic top bar */}
        <div className="pw-surface-interactive sticky top-[env(safe-area-inset-top)] z-20 mx-3 mt-3 flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs text-muted-foreground sm:mx-6 sm:mt-4 sm:px-6 sm:py-2.5">
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mr-1 px-2 lg:hidden"
              onClick={() => setMobileNavOpen(true)}
              aria-label="Open navigation"
            >
              <Menu className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Menu</span>
            </Button>
            <div className="flex items-center gap-1 mr-1">
              <button
                type="button"
                onClick={goBack}
                disabled={!canGoBack}
                aria-label="Go back"
                title="Go back"
                className="flex h-7 w-7 items-center justify-center rounded-md border border-border/40 bg-muted/30 hover:bg-muted/60 transition-colors disabled:opacity-30 disabled:pointer-events-none"
              >
                <ArrowLeft className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={goForward}
                disabled={!canGoForward}
                aria-label="Go forward"
                title="Go forward"
                className="flex h-7 w-7 items-center justify-center rounded-md border border-border/40 bg-muted/30 hover:bg-muted/60 transition-colors disabled:opacity-30 disabled:pointer-events-none"
              >
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </div>
            <span className="font-semibold text-foreground">ACE</span>
            <span className="hidden opacity-40 sm:inline">·</span>
            <span className="hidden sm:inline">
              Role: {roleLabel ? <span className="capitalize">{roleLabel}</span> : <span className="text-destructive">unavailable</span>}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <ClockPill />
            <Link to="/workspace?tab=inbox" title="Inbox" className="relative flex h-7 w-7 items-center justify-center rounded-md border border-border/40 bg-muted/30 hover:bg-muted/60">
              <Bell className="h-3.5 w-3.5" />
              {unread > 0 && <span className="absolute -right-1.5 -top-1.5 min-w-[16px] rounded-full bg-primary px-1 text-center text-[10px] font-semibold leading-4 text-primary-foreground">{unread > 99 ? "99+" : unread}</span>}
            </Link>
            <ThemeToggle />
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
                API: {API_BASE_URL || "same origin"}
              </div>
            </div>
          </div>
        </div>
        {/* Page content */}
        <div className="relative z-10 pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))] pt-4 pb-[max(2.5rem,env(safe-area-inset-bottom))] sm:px-6 sm:pt-5">
          <Outlet />
        </div>
      </main>
      <FloatingChat />
    </div>
  );
};

export default Layout;
