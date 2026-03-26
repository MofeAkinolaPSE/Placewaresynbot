import Sidebar from "./Sidebar";
import FloatingChat from "./FloatingChat";
import { Outlet } from "react-router-dom";
import { getSynbotConfig } from "@/lib/wp-config";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import { Menu } from "lucide-react";

const Layout = () => {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { role, apiBaseUrl, wpUserId } = getSynbotConfig();
  const hasRole = typeof role === "string" && role.trim().length > 0;
  const hasApiBase = typeof apiBaseUrl === "string" && apiBaseUrl.trim().length > 0;

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
            <span className="font-semibold text-foreground">PlacewareBot</span>
            <span className="opacity-40">·</span>
            <span>Role: {hasRole ? role : <span className="text-destructive">unavailable</span>}</span>
            {typeof wpUserId === "number" && (
              <span className="opacity-50">(WP User: {wpUserId})</span>
            )}
          </div>
          <div className="hidden items-center gap-2 sm:flex">
            <div className="rounded-lg border border-border/40 bg-muted/30 px-2.5 py-1">
              API: {hasApiBase ? apiBaseUrl : <span className="text-destructive">missing</span>}
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
