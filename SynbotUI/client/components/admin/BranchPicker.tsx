/**
 * Where a login works (User Access): the home branch they sign in to, and any other branch they may switch to.
 * Admin and management (CEO / CFO) always work in every branch.
 */
import { Branch } from "@/lib/branch";

const EVERY_BRANCH = ["admin", "management"];

export function BranchPicker({ branches, home, extra, roles, onChange }: {
  branches: Branch[];
  home: string;
  extra: string[];
  roles: string[];
  onChange: (home: string, extra: string[]) => void;
}) {
  if (branches.length < 2) return null;
  const everywhere = roles.some((r) => EVERY_BRANCH.includes(r));
  return (
    <div className="space-y-2 rounded-lg border p-3" data-testid="branch-picker">
      <p className="text-sm font-medium text-foreground">Branch</p>
      <div className="flex flex-wrap gap-2">
        {branches.map((b) => (
          <label key={b.id} className={`flex cursor-pointer items-center gap-2 rounded-md border px-3 py-1.5 text-sm ${home === b.id ? "border-primary bg-primary/10" : ""}`}>
            <input type="radio" name="home-branch" checked={home === b.id}
                   onChange={() => onChange(b.id, extra.filter((x) => x !== b.id))} />
            {b.branch_name}
          </label>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        They sign in to this branch and see its books, stock, customers, suppliers and Frontdesk.
      </p>
      {everywhere ? (
        <p className="text-xs text-muted-foreground">Admin and management can switch to every branch from the top bar.</p>
      ) : (
        <div className="space-y-1">
          <p className="text-xs font-medium text-foreground">Can also switch to</p>
          <div className="flex flex-wrap gap-3">
            {branches.filter((b) => b.id !== home).map((b) => (
              <label key={b.id} className="flex cursor-pointer items-center gap-2 text-sm">
                <input type="checkbox" checked={extra.includes(b.id)}
                       onChange={(e) => onChange(home, e.target.checked ? [...extra, b.id] : extra.filter((x) => x !== b.id))} />
                {b.branch_name}
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
