import { useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Loader2, RefreshCw } from "lucide-react";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { FilterBar } from "@/components/workspace/FilterBar";
import type { StaffDirectoryEntry, TimesheetEntry } from "@shared/dashboard-types";

function isStaffDirectoryEntry(staff: unknown): staff is StaffDirectoryEntry {
  if (!staff || typeof staff !== "object") return false;
  const candidate = staff as Partial<StaffDirectoryEntry>;
  return typeof candidate.full_name === "string" && typeof candidate.email === "string";
}

const DEPARTMENTS = ["Finance", "Sales", "Operations", "HR", "Management"];

// Staff Directory — full retrofit (closest precedent: ProjectControls.tsx's
// Active Projects tab). Real per-record content (staff_id, activity history
// via GET /timesheets/staff/{id}) previously had nowhere to live on the flat
// row. See ACE-Workspace-Standard.md HR chapter.
export function StaffDirectory() {
  const [search, setSearch] = useState("");
  const [department, setDepartment] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const { data: staffList, isLoading, isFetching, isError: staffError, error: staffErrorObj, refetch } = useQuery({
    queryKey: ["staff-list"],
    queryFn: () => api.staff.list(),
  });
  const { data: snapshotList, isError: snapshotError, error: snapshotErrorObj } = useQuery({
    queryKey: ["staff-snapshot"],
    queryFn: () => api.staff.snapshot(),
  });

  const liveRows = Array.isArray(staffList) ? (staffList as StaffDirectoryEntry[]) : [];
  const snapRows = Array.isArray(snapshotList) ? (snapshotList as StaffDirectoryEntry[]) : [];
  const rows: StaffDirectoryEntry[] = liveRows.length > 0 ? liveRows : snapRows;
  const usingSnapshot = liveRows.length === 0 && snapRows.length > 0;
  const validRows = useMemo(() => rows.filter(isStaffDirectoryEntry), [rows]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return validRows.filter((s) => {
      const matchQ = !q || s.full_name.toLowerCase().includes(q) || s.email.toLowerCase().includes(q);
      const matchDept = !department || s.department === department;
      return matchQ && matchDept;
    });
  }, [validRows, search, department]);

  const selected = useMemo(
    () => filtered.find((s) => String(s.staff_id ?? s.email) === selectedKey) ?? null,
    [filtered, selectedKey],
  );

  const kpis = useMemo(() => ({
    total: validRows.length,
    active: validRows.filter((s) => s.status === "active").length,
    inactive: validRows.filter((s) => s.status && s.status !== "active").length,
  }), [validRows]);

  // Only real placeware_staff rows (uuid staff_id, not the Sage snapshot
  // fallback's text id) have any chance of matching real timesheet entries —
  // the query still runs for snapshot rows, it just correctly returns empty.
  const { data: activityRaw, isLoading: activityLoading } = useQuery({
    queryKey: ["staff-activity", selected?.staff_id],
    queryFn: () => api.staff.timesheetsForStaff(String(selected!.staff_id)),
    enabled: !!selected?.staff_id,
  });
  const activity: TimesheetEntry[] = Array.isArray(activityRaw) ? activityRaw : [];

  if (!isLoading && !staffError && !snapshotError && !Array.isArray(staffList) && !Array.isArray(snapshotList)) {
    return (
      <div className="rounded-md border p-4 text-sm text-destructive">
        Data error: staff payload is unavailable or malformed.
        {staffError ? ` ${(staffErrorObj as Error)?.message || ""}` : ""}
        {snapshotError ? ` ${(snapshotErrorObj as Error)?.message || ""}` : ""}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <KpiStrip
        items={[
          { label: "Total Staff", value: kpis.total },
          { label: "Active", value: kpis.active, tone: "success" },
          { label: "Inactive", value: kpis.inactive, tone: kpis.inactive > 0 ? "warning" : "default" },
        ]}
      />

      <FilterBar
        search={{ value: search, onChange: setSearch, placeholder: "Search name or email..." }}
        selects={[
          {
            label: "Department",
            value: department,
            onChange: setDepartment,
            placeholder: "All Departments",
            options: DEPARTMENTS.map((d) => ({ value: d, label: d })),
          },
        ]}
      />

      {usingSnapshot && (
        <p className="text-xs text-muted-foreground">
          Showing latest import snapshot (not yet synced to live registry).
        </p>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr_240px] gap-4">
        {/* List Panel */}
        <Card className="lg:max-h-[600px] flex flex-col">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Staff ({filtered.length})</CardTitle>
          </CardHeader>
          <CardContent className="overflow-y-auto space-y-2 flex-1">
            {isLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : filtered.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground text-sm">
                No staff records found. Import them via the Sage Import page.
              </div>
            ) : (
              filtered.map((s) => {
                const key = String(s.staff_id ?? s.email);
                return (
                  <button
                    key={key}
                    onClick={() => setSelectedKey(key)}
                    className={`w-full text-left rounded-lg border px-3 py-2.5 hover:bg-muted/40 transition-colors ${
                      selectedKey === key ? "border-primary bg-muted/40" : ""
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-sm truncate">{s.full_name}</span>
                      <Badge variant={s.status === "active" ? "default" : "secondary"}>{s.status ?? "—"}</Badge>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground truncate">
                      {s.department || "-"}{s.role ? ` · ${s.role}` : ""}
                    </div>
                  </button>
                );
              })
            )}
          </CardContent>
        </Card>

        {/* Detail Workspace — inline, no dismiss */}
        <Card>
          <CardContent className="pt-6">
            {!selected && (
              <p className="text-sm text-muted-foreground text-center py-12">Select a staff member to view details.</p>
            )}
            {selected && (
              <div className="space-y-4 text-sm">
                <div className="flex items-start justify-between gap-2">
                  <div className="font-bold text-lg">{selected.full_name}</div>
                  <Badge variant={selected.status === "active" ? "default" : "secondary"}>{selected.status ?? "—"}</Badge>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  {[
                    ["Staff ID", selected.staff_id],
                    ["Email", selected.email],
                    ["Department", selected.department],
                    ["Role", selected.role],
                  ].map(([label, value]) => (
                    <div key={String(label)} className="space-y-0.5">
                      <div className="text-xs text-muted-foreground">{label}</div>
                      <div className="text-xs font-medium truncate">{value ?? "—"}</div>
                    </div>
                  ))}
                </div>

                <div>
                  <div className="text-xs font-semibold text-muted-foreground mb-2">RECENT ACTIVITY</div>
                  {activityLoading ? (
                    <div className="flex justify-center py-4">
                      <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                    </div>
                  ) : activity.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No recorded activity for this staff member yet.</p>
                  ) : (
                    <div className="space-y-1 max-h-64 overflow-y-auto">
                      {activity.map((entry) => (
                        <div key={entry.id} className="text-xs bg-muted/30 rounded px-2 py-1.5">
                          <div className="flex justify-between">
                            <span className="font-medium">{entry.date}</span>
                            <span className="text-muted-foreground">{Number(entry.hours_worked).toFixed(1)}h · {entry.department}</span>
                          </div>
                          {entry.activity_note && (
                            <p className="text-muted-foreground mt-0.5">{entry.activity_note}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Quick Actions */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Quick Actions</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button variant="outline" className="w-full" size="sm" onClick={() => refetch()} disabled={isFetching}>
              <RefreshCw className={`h-4 w-4 mr-1 ${isFetching ? "animate-spin" : ""}`} /> Refresh
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
