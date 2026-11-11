/**
 * The branch (Lagos / Abuja) this tab works in - always shown in the top bar, so nobody records a sale in the
 * wrong branch. Admin and management (CEO / CFO), and anyone given more than one branch on User Access, can switch
 * here; switching reloads ACE in the other branch's books, stock, customers and suppliers.
 *
 * A link with ?branch=<code> (e.g. from an "Abuja: invoice waiting for approval" notification) opens in that branch.
 */
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Building2, Check, ChevronDown } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { api } from "@/lib/api-client";
import { Branch, switchBranch } from "@/lib/branch";

const TONES = [
  "border-emerald-500/40 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300",
  "border-amber-500/50 bg-amber-500/15 text-amber-900 dark:text-amber-300",
  "border-sky-500/40 bg-sky-500/10 text-sky-900 dark:text-sky-300",
];

export function useMyBranches() {
  const { isAuthenticated } = useAuth();
  return useQuery({
    queryKey: ["branches", "me"],
    queryFn: () => api.branches.mine(),
    enabled: isAuthenticated,
    staleTime: 5 * 60_000,
  });
}

function tone(b: Branch | null | undefined, all: Branch[]) {
  const i = Math.max(0, all.findIndex((x) => x.id === b?.id));
  return TONES[i % TONES.length];
}

export function BranchSwitcher() {
  const { data } = useMyBranches();
  const location = useLocation();
  const [open, setOpen] = useState(false);

  // ?branch=<code>: open the link in that branch (when this person may use it)
  useEffect(() => {
    if (!data) return;
    const want = new URLSearchParams(location.search).get("branch");
    if (!want) return;
    const target = data.branches.find((b) => b.code === want || b.id === want);
    if (target && target.id !== data.current?.id) {
      const params = new URLSearchParams(location.search);
      params.delete("branch");
      const rest = params.toString();
      switchBranch(target.id, `${location.pathname}${rest ? `?${rest}` : ""}`);
    }
  }, [data, location.pathname, location.search]);

  if (!data?.current) return null;
  const cur = data.current;
  const cls = `flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-semibold ${tone(cur, data.branches)}`;
  if (!data.can_switch) {
    return (
      <span className={cls} title={`You are working in ${cur.branch_name} - ${cur.name}`} data-testid="branch-badge">
        <Building2 className="h-3.5 w-3.5" />
        {cur.branch_name}
      </span>
    );
  }
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen((v) => !v)} className={`${cls} hover:opacity-90`}
              title="Branch - switch between the branches' books, stock, customers and suppliers" data-testid="branch-switcher">
        <Building2 className="h-3.5 w-3.5" />
        {cur.branch_name}
        <ChevronDown className="h-3 w-3 opacity-70" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute left-0 z-40 mt-1 w-64 overflow-hidden rounded-lg border bg-card shadow-lg sm:left-auto sm:right-0">
            <div className="border-b px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Work in branch</div>
            <ul>
              {data.branches.map((b) => (
                <li key={b.id}>
                  <button type="button" disabled={b.id === cur.id}
                          onClick={() => { setOpen(false); switchBranch(b.id); }}
                          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-muted/60 disabled:cursor-default">
                    <span className={`h-2.5 w-2.5 rounded-full border ${tone(b, data.branches)}`} />
                    <span className="flex-1">
                      <span className="block font-medium text-foreground">{b.branch_name}</span>
                      <span className="block text-muted-foreground">{b.name}</span>
                    </span>
                    {b.id === cur.id && <Check className="h-3.5 w-3.5 text-primary" />}
                  </button>
                </li>
              ))}
            </ul>
            <div className="border-t px-3 py-2 text-[11px] leading-snug text-muted-foreground">
              Each branch has its own books, stock, customers, suppliers and Frontdesk. HR, My Workspace and chat are shared.
            </div>
          </div>
        </>
      )}
    </div>
  );
}
