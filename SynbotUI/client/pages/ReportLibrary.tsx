/**
 * ReportLibrary — searchable, filterable table of all stored reports.
 *
 * Features:
 *  - Filter by report type, approval status, date range
 *  - Quality score badge (colour-coded)
 *  - Download DOCX (DRAFT / FINAL)
 *  - Navigate to /reports/new for generation
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Plus,
  Download,
  RefreshCw,
  Loader2,
  CheckCircle,
  Clock,
  AlertCircle,
  FileText,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api-client";
import { useToast } from "@/hooks/use-toast";

// ── Helpers ───────────────────────────────────────────────────────────────────

function ApprovalBadge({ status }: { status: string }) {
  if (status === "approved")
    return (
      <Badge className="bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300 border-0">
        <CheckCircle className="w-3 h-3 mr-1" /> Approved
      </Badge>
    );
  if (status === "complete")
    return (
      <Badge className="bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300 border-0">
        <Clock className="w-3 h-3 mr-1" /> Complete
      </Badge>
    );
  return (
    <Badge variant="outline" className="text-muted-foreground">
      <AlertCircle className="w-3 h-3 mr-1" /> Draft
    </Badge>
  );
}

function ScoreBadge({ score }: { score?: number }) {
  if (score == null) return <span className="text-muted-foreground text-xs">–</span>;
  const cls =
    score >= 8
      ? "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300"
      : score >= 6
      ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300"
      : "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300";
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-bold ${cls}`}>
      {score.toFixed(1)}
    </span>
  );
}

// Radix Select throws on <SelectItem value="">, so "all" is used as the
// sentinel for the unfiltered state and mapped back to "" in state.
const REPORT_TYPE_OPTIONS = [
  { value: "all", label: "All Types" },
  { value: "executive", label: "Executive" },
  { value: "financial", label: "Financial" },
  { value: "sales", label: "Sales" },
  { value: "inventory", label: "Inventory" },
  { value: "payroll", label: "Payroll" },
  { value: "pl", label: "Profit & Loss" },
  { value: "ar_aging", label: "AR Aging" },
  { value: "compliance", label: "Compliance" },
  { value: "audit", label: "Audit" },
  { value: "deviation", label: "Deviation" },
  { value: "maintenance", label: "Maintenance" },
  { value: "frontdesk", label: "Frontdesk" },
  { value: "invoice", label: "Invoice" },
];

const STATUS_OPTIONS = [
  { value: "all", label: "All Statuses" },
  { value: "draft", label: "Draft" },
  { value: "complete", label: "Complete" },
  { value: "approved", label: "Approved" },
];

// ── Main component ────────────────────────────────────────────────────────────
export default function ReportLibrary() {
  const { toast } = useToast();
  const [typeFilter, setTypeFilter]     = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch]             = useState("");
  const [limit, setLimit]               = useState(20);
  const [downloading, setDownloading]   = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["report-library", typeFilter, statusFilter, limit],
    queryFn: () =>
      api.reports.history(typeFilter || undefined, limit),
    refetchOnWindowFocus: false,
  });

  const reports: any[] = data?.reports ?? [];

  // Client-side search filter
  const filtered = reports.filter((r) => {
    const term = search.toLowerCase();
    if (statusFilter && r.approval_status !== statusFilter) return false;
    if (!term) return true;
    return (
      r.report_type?.toLowerCase().includes(term) ||
      r.summary?.toLowerCase().includes(term) ||
      r.subject_label?.toLowerCase().includes(term) ||
      r.id?.toLowerCase().includes(term)
    );
  });

  const handleDownload = async (reportId: string) => {
    setDownloading(reportId);
    try {
      const { url, filename } = await api.reports.downloadDocx(reportId);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      toast({ title: "Download failed", description: err.message, variant: "destructive" });
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Report Library</h1>
          <p className="text-sm text-muted-foreground">
            View, download, and approve generated reports.
          </p>
        </div>
        <Link to="/reports/new">
          <Button className="bg-green-700 hover:bg-green-800 text-white">
            <Plus className="w-4 h-4 mr-1" /> New Report
          </Button>
        </Link>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex flex-wrap gap-3 items-center">
            <Input
              placeholder="Search by type, summary, or ID…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-64"
            />
            <Select value={typeFilter || "all"} onValueChange={(v) => setTypeFilter(v === "all" ? "" : v)}>
              <SelectTrigger className="w-44">
                <SelectValue placeholder="Report Type" />
              </SelectTrigger>
              <SelectContent>
                {REPORT_TYPE_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={statusFilter || "all"} onValueChange={(v) => setStatusFilter(v === "all" ? "" : v)}>
              <SelectTrigger className="w-40">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              disabled={isLoading}
            >
              <RefreshCw className={`w-4 h-4 mr-1 ${isLoading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {filtered.length} report{filtered.length !== 1 ? "s" : ""}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center gap-2 p-6 text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin" /> Loading reports…
            </div>
          ) : error ? (
            <div className="p-6 text-red-500 text-sm">Failed to load reports. Try refreshing.</div>
          ) : filtered.length === 0 ? (
            <div className="p-12 text-center text-muted-foreground">
              <FileText className="w-10 h-10 mx-auto mb-3 opacity-30" />
              <p className="font-medium">No reports found</p>
              <p className="text-sm mt-1">Generate your first report using the wizard.</p>
              <Link to="/reports/new">
                <Button className="mt-4" size="sm">
                  <Plus className="w-4 h-4 mr-1" /> Generate Report
                </Button>
              </Link>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/40">
                    <th className="text-left p-3 font-medium text-muted-foreground">Type</th>
                    <th className="text-left p-3 font-medium text-muted-foreground">Summary</th>
                    <th className="text-left p-3 font-medium text-muted-foreground">Score</th>
                    <th className="text-left p-3 font-medium text-muted-foreground">Status</th>
                    <th className="text-left p-3 font-medium text-muted-foreground">Version</th>
                    <th className="text-left p-3 font-medium text-muted-foreground">Date</th>
                    <th className="text-left p-3 font-medium text-muted-foreground">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((r) => (
                    <tr
                      key={r.id}
                      className="border-b last:border-0 hover:bg-muted/30 transition-colors"
                    >
                      <td className="p-3">
                        <Badge variant="outline" className="capitalize">
                          {r.report_type?.replace(/_/g, " ") ?? "–"}
                        </Badge>
                      </td>
                      <td className="p-3 max-w-xs">
                        {r.subject_label && (
                          <Link to={`/reports/new?${new URLSearchParams({ type: r.report_type, kind: r.subject_kind, id: r.subject_id })}`}
                            className="block truncate text-sm font-medium hover:text-primary" title="Open this record's information / write another report on it">
                            {r.subject_label}
                          </Link>
                        )}
                        <p className="truncate text-sm text-muted-foreground" title={r.summary}>
                          {r.summary ?? <span className="text-muted-foreground italic">No summary</span>}
                        </p>
                      </td>
                      <td className="p-3">
                        <ScoreBadge score={r.quality_score} />
                      </td>
                      <td className="p-3">
                        <ApprovalBadge status={r.approval_status ?? "draft"} />
                      </td>
                      <td className="p-3 text-xs text-muted-foreground">
                        {r.template_version ?? "–"}
                      </td>
                      <td className="p-3 text-xs text-muted-foreground whitespace-nowrap">
                        {r.created_at
                          ? new Date(r.created_at).toLocaleDateString("en-NG", {
                              day: "2-digit",
                              month: "short",
                              year: "numeric",
                            })
                          : "–"}
                      </td>
                      <td className="p-3">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDownload(r.id)}
                          disabled={downloading === r.id}
                          className="h-7 px-2"
                        >
                          {downloading === r.id ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Download className="w-3.5 h-3.5" />
                          )}
                          <span className="ml-1">DOCX</span>
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Load more */}
      {filtered.length >= limit && (
        <div className="flex justify-center">
          <Button variant="outline" onClick={() => setLimit((l) => l + 20)}>
            Load more
          </Button>
        </div>
      )}
    </div>
  );
}
