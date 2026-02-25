import { TrendingUp, AlertTriangle } from "lucide-react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from "recharts";
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

const CRM = () => {
  const { data: fetchedData, isLoading, isError, error } = useQuery({
    queryKey: ["crm-dashboard"],
    queryFn: () => api.dashboard.crm(),
  });
  const { data: riskRaw, isError: riskIsError, error: riskError } = useQuery({
    queryKey: ["crm-risk-scores"],
    queryFn: () => api.crm.riskScores(),
  });

  const dataValid =
    !!fetchedData &&
    typeof (fetchedData as any).pipeline_value === "number" &&
    typeof (fetchedData as any).active_opps === "number" &&
    typeof (fetchedData as any).win_rate === "number" &&
    typeof (fetchedData as any).avg_risk_score === "number" &&
    Array.isArray((fetchedData as any).recent_deals);

  const riskCustomers =
    riskRaw && Array.isArray((riskRaw as any).customers)
      ? (riskRaw as any).customers
      : [];

  const data = dataValid
    ? (fetchedData as any)
    : {
        pipeline_value: 0,
        active_opps: 0,
        win_rate: 0,
        avg_risk_score: 0,
        recent_deals: [],
      };
  const riskByCustomer: Record<string, { risk_score: number; overdue_ar_amount: number }> = {};
  (riskCustomers as any[]).forEach((c) => {
    const cid = String(c.customer_id ?? "");
    if (!cid) return;
    riskByCustomer[cid] = {
      risk_score: Number(c.risk_score ?? 0),
      overdue_ar_amount: Number(c.overdue_ar_amount ?? 0),
    };
  });

  const kpis = [
    {
      label: "Pipeline Value",
      value: `₦${(data.pipeline_value / 1000000).toFixed(1)}M`,
      change: "",
      sublabel: `${data.active_opps} active opportunities`,
    },
    {
      label: "Win Rate %",
      value: `${data.win_rate.toFixed(1)}%`,
      change: "",
      sublabel: "Closed won vs total",
    },
    {
      label: "Risk Score",
      value: data.avg_risk_score.toFixed(1),
      change: "",
      sublabel: "Average (0-100 scale)",
    },
    {
      label: "Sales Cycle",
      value: "Data unavailable",
      change: "",
      sublabel: "Insufficient Data",
    },
  ];

  const pipelineTrendData = [{ month: "Current", value: data.pipeline_value / 1000000, forecast: 0 }];
  const winLossData = [{ month: "Current", won: data.win_rate, lost: 100 - data.win_rate, rate: data.win_rate }];

  const opportunitiesData = (data.recent_deals || []).map((d: any, i: number) => {
    const customerId = String(d.customer_id ?? "");
    const riskInfo = customerId ? riskByCustomer[customerId] : undefined;
    const riskScore = riskInfo?.risk_score ?? 0;
    const overdueAmount = riskInfo?.overdue_ar_amount ?? 0;

    const riskFlag = (() => {
      if (riskScore >= 70) return "high";
      if (riskScore >= 40) return "medium";
      return "low";
    })();

    const arStatus = overdueAmount > 0 ? "overdue" : "current";

    return {
      id: i,
      customer: customerId,
      value: Number(d.amount),
      stage: d.stage || d.status || "unknown",
      riskFlag,
      arStatus,
      closeDate: d.close_date,
    };
  }).filter((d: any) => typeof d.customer === "string" && d.customer.length > 0 && Number.isFinite(d.value) && typeof d.closeDate === "string");

  const getRiskColor = (risk: string) => {
    switch (risk) {
      case "high":
        return "bg-red-100 text-red-800";
      case "medium":
        return "bg-yellow-100 text-yellow-800";
      case "low":
        return "bg-green-100 text-green-800";
      default:
        return "bg-gray-100 text-gray-800";
    }
  };

  const getARStatusColor = (status: string) => {
    return status === "overdue"
      ? "bg-red-50 text-red-700"
      : "bg-green-50 text-green-700";
  };

  const totalPipeline = data.pipeline_value;

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-foreground">CRM</h1>
        <p className="text-muted-foreground mt-2">
          Revenue & risk visibility for Placeware Nigeria sales pipeline
        </p>
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">Loading CRM data...</p>}
      {(isError || (!isLoading && !dataValid)) && (
        <p className="text-sm text-destructive">
          Data error: CRM dashboard payload is unavailable or malformed.
          {isError ? ` ${(error as Error)?.message || ""}` : ""}
        </p>
      )}

      {/* KPI Grid */}
      {riskIsError && (
        <p className="text-sm text-destructive">Risk data error: {(riskError as Error)?.message || "Failed to load CRM risk scores."}</p>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {kpis.map((kpi, idx) => (
          <div
            key={idx}
            className="bg-card border border-border rounded-lg p-6 hover:shadow-lg transition-shadow"
          >
            <p className="text-sm font-medium text-muted-foreground mb-1">
              {kpi.label}
            </p>
            <h3 className="text-2xl font-bold text-foreground mb-3">
              {dataValid ? kpi.value : (isLoading ? "Loading..." : "-")}
            </h3>
            <div className="flex items-center gap-2 mb-2">
              <TrendingUp className="w-4 h-4 text-warning" />
              <span className="text-sm font-medium text-warning">
                {kpi.change}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">{kpi.sublabel}</p>
          </div>
        ))}
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Pipeline Trend */}
        <div className="bg-card border border-border rounded-lg p-6">
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-foreground">
              Pipeline Trend
            </h2>
            <p className="text-sm text-muted-foreground">
              Monthly sales pipeline value (₦M)
            </p>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={pipelineTrendData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="month" stroke="#6b7280" angle={-45} height={80} />
              <YAxis stroke="#6b7280" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#ffffff",
                  border: "1px solid #e5e7eb",
                  borderRadius: "8px",
                }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="value"
                stroke="#0064cc"
                strokeWidth={2}
                name="Pipeline"
                dot={{ r: 4 }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Win/Loss Ratio */}
        <div className="bg-card border border-border rounded-lg p-6">
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-foreground">
              Win/Loss Ratio
            </h2>
            <p className="text-sm text-muted-foreground">
              Closed opportunities by outcome
            </p>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={winLossData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="month" stroke="#6b7280" angle={-45} height={80} />
              <YAxis stroke="#6b7280" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#ffffff",
                  border: "1px solid #e5e7eb",
                  borderRadius: "8px",
                }}
              />
              <Legend />
              <Bar dataKey="won" fill="#219653" name="Won" />
              <Bar dataKey="lost" fill="#ef4444" name="Lost" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Opportunities Table */}
      <div className="bg-card border border-border rounded-lg p-6">
        <div className="mb-4">
          <h2 className="text-lg font-semibold text-foreground">
            Active Opportunities
          </h2>
          <p className="text-sm text-muted-foreground">
            {opportunitiesData.length} open opportunities worth ₦
            {(totalPipeline / 1000000).toFixed(1)}M
          </p>
        </div>

        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Customer</TableHead>
                <TableHead className="text-right">Value (₦)</TableHead>
                <TableHead>Stage</TableHead>
                <TableHead>Risk</TableHead>
                <TableHead>AR Status</TableHead>
                <TableHead>Est. Close Date</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {opportunitiesData.map((opp) => (
                <TableRow key={opp.id}>
                  <TableCell className="font-medium">{opp.customer}</TableCell>
                  <TableCell className="text-right font-mono">
                    {(opp.value / 1000000).toFixed(1)}M
                  </TableCell>
                  <TableCell>
                    <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs font-medium">
                      {opp.stage}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      {opp.riskFlag === "high" && (
                        <AlertTriangle className="w-4 h-4 text-red-600" />
                      )}
                      <span
                        className={`px-2 py-1 rounded text-xs font-medium inline-block ${getRiskColor(
                          opp.riskFlag
                        )}`}
                      >
                        {opp.riskFlag.charAt(0).toUpperCase() +
                          opp.riskFlag.slice(1)}{" "}
                        Risk
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <span
                      className={`px-2 py-1 rounded text-xs font-medium inline-block ${getARStatusColor(
                        opp.arStatus
                      )}`}
                    >
                      {opp.arStatus === "overdue" ? "Overdue AR" : "Current AR"}
                    </span>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {opp.closeDate}
                  </TableCell>
                </TableRow>
              ))}
              {opportunitiesData.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-destructive py-8">
                    Data error: no valid opportunities returned from backend.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>

        {/* Risk Summary */}
        <div className="grid grid-cols-3 gap-4 mt-6">
          <div className="bg-red-50 rounded-lg p-4">
            <p className="text-xs font-semibold text-red-800 uppercase">
              High Risk
            </p>
            <p className="text-lg font-bold text-red-900 mt-2">
              {opportunitiesData.filter((o) => o.riskFlag === "high").length}
            </p>
            <p className="text-xs text-red-700 mt-1">
              ₦
              {(
                opportunitiesData
                  .filter((o) => o.riskFlag === "high")
                  .reduce((sum, o) => sum + o.value, 0) / 1000000
              ).toFixed(1)}
              M at risk
            </p>
          </div>
          <div className="bg-yellow-50 rounded-lg p-4">
            <p className="text-xs font-semibold text-yellow-800 uppercase">
              Medium Risk
            </p>
            <p className="text-lg font-bold text-yellow-900 mt-2">
              {opportunitiesData.filter((o) => o.riskFlag === "medium").length}
            </p>
            <p className="text-xs text-yellow-700 mt-1">
              ₦
              {(
                opportunitiesData
                  .filter((o) => o.riskFlag === "medium")
                  .reduce((sum, o) => sum + o.value, 0) / 1000000
              ).toFixed(1)}
              M at risk
            </p>
          </div>
          <div className="bg-green-50 rounded-lg p-4">
            <p className="text-xs font-semibold text-green-800 uppercase">
              Low Risk
            </p>
            <p className="text-lg font-bold text-green-900 mt-2">
              {opportunitiesData.filter((o) => o.riskFlag === "low").length}
            </p>
            <p className="text-xs text-green-700 mt-1">
              ₦
              {(
                opportunitiesData
                  .filter((o) => o.riskFlag === "low")
                  .reduce((sum, o) => sum + o.value, 0) / 1000000
              ).toFixed(1)}
              M
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CRM;
