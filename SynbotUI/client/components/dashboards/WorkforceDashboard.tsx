import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { WorkforceDashboardData } from "@shared/dashboard-types";
import { Users, Clock, Building2 } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";

export function WorkforceDashboard({ data: initialData }: { data?: WorkforceDashboardData }) {
  const { data: fetchedData, isLoading, error } = useQuery({
    queryKey: ["dashboard-workforce"],
    queryFn: () => api.dashboard.workforce(),
    enabled: !initialData
  });

  const data = initialData || fetchedData;

  const workforceValid =
    !!data &&
    typeof data.active_staff_count === "number" &&
    typeof data.total_hours === "number" &&
    typeof data.department_breakdown === "object";

  const chartData = Object.entries(workforceValid ? data.department_breakdown : {}).map(([name, value]) => ({
    name,
    hours: value
  }));

  const topDepartment = (() => {
    const entries = Object.entries(workforceValid ? data.department_breakdown : {});
    if (!entries.length) return "-";
    return entries.reduce((best, current) => (current[1] > best[1] ? current : best))[0];
  })();

  return (
    <div className="flex flex-col gap-4">
      {error && (
        <div className="text-sm text-destructive">
          Data error: workforce payload is unavailable or malformed.
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="border-l-4 border-l-primary">
          <CardHeader className="pb-1 pt-4">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Active Staff</CardTitle>
              <Users className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="text-3xl font-bold tabular-nums">{workforceValid ? data.active_staff_count : (isLoading ? "Loading..." : "—")}</div>
            <p className="mt-1 text-xs text-muted-foreground">Registered in system</p>
          </CardContent>
        </Card>

        <Card className="border-l-4 border-l-info">
          <CardHeader className="pb-1 pt-4">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Hours Logged (Week)</CardTitle>
              <Clock className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="text-3xl font-bold tabular-nums">{workforceValid ? data.total_hours : (isLoading ? "..." : "—")}</div>
            <p className="mt-1 text-xs text-muted-foreground">Total operational effort</p>
          </CardContent>
        </Card>

        <Card className="border-l-4 border-l-secondary">
          <CardHeader className="pb-1 pt-4">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Top Department</CardTitle>
              <Building2 className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="text-3xl font-bold">{topDepartment}</div>
            <p className="mt-1 text-xs text-muted-foreground">Highest activity level</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base font-semibold">Departmental Effort Distribution</CardTitle>
        </CardHeader>
        <CardContent className="px-2 pb-4">
          <div className="h-[320px] w-full">
              {chartData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 8, right: 12, left: 4, bottom: 8 }}>
                    <XAxis dataKey="name" fontSize={12} tickLine={false} axisLine={false} stroke="hsl(var(--muted-foreground))" />
                    <YAxis fontSize={12} tickLine={false} axisLine={false} tickFormatter={(value) => `${value}h`} stroke="hsl(var(--muted-foreground))" width={52} />
                    <Tooltip contentStyle={{ fontSize: "13px", borderRadius: "8px" }} />
                    <Bar dataKey="hours" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  {isLoading ? "Loading departmental distribution..." : "No departmental distribution available."}
                </div>
              )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
