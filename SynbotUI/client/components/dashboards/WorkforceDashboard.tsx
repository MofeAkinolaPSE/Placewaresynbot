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
    <div className="space-y-6">
      {error && (
        <div className="text-sm text-destructive">
          Data error: workforce payload is unavailable or malformed.
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Staff</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{workforceValid ? data.active_staff_count : (isLoading ? "Loading..." : "-")}</div>
            <p className="text-xs text-muted-foreground">Registered in system</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Hours Logged (Week)</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{workforceValid ? data.total_hours : (isLoading ? "..." : "-")}</div>
            <p className="text-xs text-muted-foreground">Total operational effort</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Top Department</CardTitle>
            <Building2 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {/* Logic to find top dept */}
            <div className="text-2xl font-bold">
               {topDepartment}
            </div>
            <p className="text-xs text-muted-foreground">Highest activity level</p>
          </CardContent>
        </Card>
      </div>

      <Card className="col-span-4">
        <CardHeader>
          <CardTitle>Departmental Effort Distribution</CardTitle>
        </CardHeader>
        <CardContent className="pl-2">
          <div className="h-[200px] w-full">
              {chartData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData}>
                    <XAxis dataKey="name" stroke="#888888" fontSize={12} tickLine={false} axisLine={false} />
                    <YAxis stroke="#888888" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(value) => `${value}h`} />
                    <Tooltip />
                    <Bar dataKey="hours" fill="#0f172a" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-sm text-muted-foreground">
                  {isLoading ? "Loading departmental distribution..." : "No departmental distribution available."}
                </div>
              )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
