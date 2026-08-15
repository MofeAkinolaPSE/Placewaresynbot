import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { WorkforceDashboardData } from "@shared/dashboard-types";
import { Users, Clock, Building2, Circle } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { KpiStrip } from "@/components/workspace/KpiStrip";

export function WorkforceDashboard({ data: initialData }: { data?: WorkforceDashboardData }) {
  const { data: fetchedData, isLoading, error } = useQuery({
    queryKey: ["dashboard-workforce"],
    queryFn: () => api.dashboard.workforce(),
    enabled: !initialData
  });

  // Same query key Layout.tsx's top-bar pill uses -- TanStack Query dedupes
  // this automatically, no extra network cost for having it in both places.
  const { data: presenceData } = useQuery({
    queryKey: ["presence-online"],
    queryFn: () => api.presence.online(),
    refetchInterval: 30_000,
  });
  const onlineCount = presenceData?.count ?? 0;

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
      <KpiStrip
        items={[
          // "Currently Online" (real-time presence) is a genuinely different
          // metric from the one below it -- renamed from "Active Staff" to
          // avoid the two being confused for the same thing.
          { label: "Currently Online", value: onlineCount, icon: Circle, tone: onlineCount > 0 ? "success" : "default" },
          { label: "Staff Logged Time (Week)", value: workforceValid ? data.active_staff_count : (isLoading ? "Loading..." : "—"), icon: Users },
          { label: "Hours Logged (Week)", value: workforceValid ? data.total_hours : (isLoading ? "..." : "—"), icon: Clock },
          { label: "Top Department", value: topDepartment, icon: Building2 },
        ]}
      />

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
