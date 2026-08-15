import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useIsMobile } from "@/hooks/use-mobile";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { FilterBar } from "@/components/workspace/FilterBar";
import type { TimesheetEntry } from "@shared/dashboard-types";

function isTimesheetEntry(row: unknown): row is TimesheetEntry {
  if (!row || typeof row !== "object") return false;
  const candidate = row as Partial<TimesheetEntry>;
  return (
    (typeof candidate.id === "number" || typeof candidate.id === "string") &&
    typeof candidate.date === "string" &&
    typeof candidate.department === "string" &&
    Number.isFinite(Number(candidate.hours_worked))
  );
}

const DEPARTMENTS = ["Finance", "Sales", "Operations", "HR", "Management"];

function staffLabel(row: TimesheetEntry): string {
  return typeof row.staff?.full_name === "string" ? row.staff.full_name : String(row.staff_id || "");
}

// Timesheets — partial retrofit (closest precedent: PurchaseOrders.tsx). A
// flat log where every row already shows what's relevant; no per-row detail
// to surface beyond the row itself. See ACE-Workspace-Standard.md HR chapter.
export function TimesheetsTable() {
  const isMobile = useIsMobile();
  const [search, setSearch] = useState("");
  const [department, setDepartment] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["timesheets"],
    queryFn: () => api.staff.timesheets(undefined, 200),
    refetchInterval: 60000,
  });

  const payloadValid = Array.isArray(data);
  const dataError = !isLoading && (error || !payloadValid);

  const allRows: TimesheetEntry[] = (payloadValid ? data : []).filter(isTimesheetEntry);
  const malformedCount = (payloadValid ? data.length : 0) - allRows.length;

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return allRows.filter((row) => {
      const matchQ = !q || staffLabel(row).toLowerCase().includes(q);
      const matchDept = !department || row.department === department;
      return matchQ && matchDept;
    });
  }, [allRows, search, department]);

  const kpis = useMemo(() => ({
    entries: rows.length,
    totalHours: rows.reduce((s, r) => s + (Number(r.hours_worked) || 0), 0),
    uniqueStaff: new Set(rows.map((r) => r.staff_id ?? staffLabel(r))).size,
  }), [rows]);

  return (
    <div className="space-y-4">
      <KpiStrip
        items={[
          { label: "Entries", value: kpis.entries },
          { label: "Total Hours", value: kpis.totalHours.toFixed(1) },
          { label: "Unique Staff Logged", value: kpis.uniqueStaff },
        ]}
      />

      <FilterBar
        search={{ value: search, onChange: setSearch, placeholder: "Search staff name..." }}
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

      <div className="rounded-md border bg-card">
        {isLoading && (
          <div className="px-4 py-2 text-sm text-muted-foreground border-b">
            Loading timesheets...
          </div>
        )}
        {dataError && (
          <div className="px-4 py-2 text-sm text-destructive border-b">
            Data error: {(error as Error)?.message || "Malformed timesheets payload."}
          </div>
        )}
        {malformedCount > 0 && (
          <div className="px-4 py-2 text-sm text-destructive border-b">
            Data error: {malformedCount} timesheet row(s) were malformed and excluded.
          </div>
        )}
        {isMobile ? (
          <div className="space-y-3 p-4">
            {rows.length > 0 ? (
              rows.map((row) => (
                <div key={row.id} className="rounded-lg border border-border/60 bg-muted/20 p-3 space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-semibold text-foreground">{staffLabel(row)}</p>
                    <p className="font-mono text-sm text-foreground">{Number(row.hours_worked).toFixed(2)}h</p>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span>{row.date}</span>
                    <span>•</span>
                    <span>{row.department}</span>
                  </div>
                  <p className="text-xs text-muted-foreground break-words">
                    {typeof row.activity_note === "string" ? row.activity_note : ""}
                  </p>
                </div>
              ))
            ) : (
              <p className="text-center text-muted-foreground py-6">
                No timesheet data uploaded yet. Once teams start recording hours in Placeware,
                entries will appear here automatically.
              </p>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[120px]">Date</TableHead>
                  <TableHead className="sticky left-0 z-10 min-w-[180px] bg-muted/90">Staff</TableHead>
                  <TableHead className="min-w-[140px]">Department</TableHead>
                  <TableHead className="text-right min-w-[120px]">Hours Worked</TableHead>
                  <TableHead className="min-w-[280px]">Activity</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.length > 0 ? (
                  rows.map((row) => (
                    <TableRow key={row.id}>
                      <TableCell className="text-sm text-muted-foreground">
                        {row.date}
                      </TableCell>
                      <TableCell className="sticky left-0 z-10 bg-background font-medium">
                        {staffLabel(row)}
                      </TableCell>
                      <TableCell>{row.department}</TableCell>
                      <TableCell className="text-right font-mono">
                        {Number(row.hours_worked).toFixed(2)}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground max-w-xs truncate">
                        {typeof row.activity_note === "string" ? row.activity_note : ""}
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center py-10">
                      <p className="text-muted-foreground">
                        No timesheet data uploaded yet. Once teams start recording hours in Placeware,
                        entries will appear here automatically.
                      </p>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );
}
