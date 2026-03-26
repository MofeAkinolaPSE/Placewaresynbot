import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { useIsMobile } from "@/hooks/use-mobile";

export function StaffDirectory() {
  const isMobile = useIsMobile();
  const { data: staffList, isLoading, isError: staffError, error: staffErrorObj } = useQuery({
    queryKey: ["staff-list"],
    queryFn: () => api.staff.list(),
  });
  const { data: snapshotList, isError: snapshotError, error: snapshotErrorObj } = useQuery({
    queryKey: ["staff-snapshot"],
    queryFn: () => api.staff.snapshot(),
  });

  // Backend response shape is { data: [...] } from staff router
  // But wait, staff router in staff_ops.py:
  // "return {"data": get_staff_by_department(department)}"
  // And api-client.ts says: "return res.json().then(d => d.data)"
  // So staffList here should be the array itself.

  const liveRows = Array.isArray(staffList) ? (staffList as any[]) : [];
  const snapRows = Array.isArray(snapshotList) ? (snapshotList as any[]) : [];
  const rows: any[] = liveRows.length > 0 ? liveRows : snapRows;
  const usingSnapshot = liveRows.length === 0 && snapRows.length > 0;

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
    <div className="rounded-md border">
      {isLoading && (
        <div className="p-3 text-xs text-muted-foreground border-b">
          Loading staff directory...
        </div>
      )}
      {usingSnapshot && (
        <div className="p-3 text-xs text-muted-foreground border-b">
          Showing latest import snapshot (not yet synced to live registry).
        </div>
      )}
      {isMobile ? (
        <div className="space-y-3 p-4">
          {rows.filter((staff: any) => typeof staff?.full_name === "string" && typeof staff?.email === "string").map((staff) => (
            <div key={staff.staff_id ?? staff.email} className="rounded-lg border border-border/60 bg-muted/20 p-3 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <p className="font-medium text-foreground">{staff.full_name}</p>
                <Badge variant={staff.status === "active" ? "default" : "secondary"}>
                  {staff.status}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground break-all">{staff.email}</p>
              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span>{staff.department}</span>
                {typeof staff.role === "string" && staff.role ? (
                  <>
                    <span>•</span>
                    <span>{staff.role}</span>
                  </>
                ) : null}
              </div>
            </div>
          ))}
          {rows.length === 0 && (
            <p className="text-center text-muted-foreground py-6">
              No staff records found. Import them via the Sage Import page.
            </p>
          )}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="sticky left-0 z-10 min-w-[180px] bg-muted/90">Full Name</TableHead>
                <TableHead className="min-w-[220px]">Email</TableHead>
                <TableHead className="min-w-[130px]">Department</TableHead>
                <TableHead className="min-w-[100px]">Role</TableHead>
                <TableHead className="min-w-[90px]">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.filter((staff: any) => typeof staff?.full_name === "string" && typeof staff?.email === "string").map((staff) => (
                <TableRow key={staff.staff_id ?? staff.email}>
                  <TableCell className="sticky left-0 z-10 bg-background font-medium">{staff.full_name}</TableCell>
                  <TableCell>{staff.email}</TableCell>
                  <TableCell>{staff.department}</TableCell>
                  <TableCell>{typeof staff.role === "string" ? staff.role : ""}</TableCell>
                  <TableCell>
                    <Badge variant={staff.status === "active" ? "default" : "secondary"}>
                      {staff.status}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
              {rows.length === 0 && (
                 <TableRow>
                    <TableCell colSpan={5} className="text-center h-24">
                       No staff records found. Import them via the Sage Import page.
                    </TableCell>
                 </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
