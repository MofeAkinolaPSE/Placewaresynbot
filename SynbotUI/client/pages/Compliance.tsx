import { useState, useCallback, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ShieldCheck,
  AlertTriangle,
  ClipboardList,
  Wrench,
  PackageX,
  FileText,
  Plus,
  CheckCircle,
  XCircle,
  Download,
  Upload,
  RefreshCw,
  Loader2,
  TrendingUp,
  TrendingDown,
  Activity,
  Database,
  Eye,
} from "lucide-react";
import { api } from "@/lib/api-client";
import { useAuth } from "@/components/AuthProvider";
import { useToast } from "@/hooks/use-toast";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { useIsMobile } from "@/hooks/use-mobile";
import { useNavigate } from "react-router-dom";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { FilterBar } from "@/components/workspace/FilterBar";
import { DetailSheet } from "@/components/workspace/DetailSheet";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function statusBadge(status: string) {
  const map: Record<string, string> = {
    completed: "bg-green-500/20 text-green-400 border-green-500/30",
    in_progress: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    scheduled: "bg-slate-500/20 text-slate-300 border-slate-500/30",
    overdue: "bg-red-500/20 text-red-400 border-red-500/30",
    open: "bg-orange-500/20 text-orange-400 border-orange-500/30",
    closed: "bg-green-500/20 text-green-400 border-green-500/30",
    active: "bg-red-500/20 text-red-400 border-red-500/30",
    resolved: "bg-green-500/20 text-green-400 border-green-500/30",
    draft: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    pending: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  };
  const cls = map[status?.toLowerCase()] ?? "bg-slate-500/20 text-slate-300 border-slate-500/30";
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold", cls)}>
      {status?.replace(/_/g, " ")}
    </span>
  );
}

function severityBadge(severity: string) {
  const map: Record<string, string> = {
    critical: "bg-red-600/25 text-red-300 border-red-600/40",
    major: "bg-orange-500/25 text-orange-300 border-orange-500/40",
    minor: "bg-yellow-500/25 text-yellow-300 border-yellow-500/40",
    low: "bg-slate-500/20 text-slate-300 border-slate-500/30",
  };
  const cls = map[severity?.toLowerCase()] ?? "bg-slate-500/20 text-slate-300 border-slate-500/30";
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold", cls)}>
      {severity}
    </span>
  );
}

function formatDate(d?: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

// ─── Documents Tab ────────────────────────────────────────────────────────────

const DOC_TYPE_FILTERS = [
  { label: "All", value: "" },
  { label: "Audit Reports", value: "audit_report" },
  { label: "Deviation Reports", value: "deviation_report" },
  { label: "CAPA", value: "capa" },
  { label: "SOPs", value: "sop" },
  { label: "Recall Documents", value: "recall" },
];

function DocumentsTab() {
  const { roles } = useAuth();
  const isMobile = useIsMobile();
  const { toast } = useToast();
  const qc = useQueryClient();
  const [docTypeFilter, setDocTypeFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [viewDoc, setViewDoc] = useState<any | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const canUpload = roles.some((r) => ["admin", "quality", "quality_assurance", "qa"].includes(r));

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["knowledge-documents", docTypeFilter],
    queryFn: () => api.knowledge.getDocuments(docTypeFilter || undefined),
  });

  const { data: viewData, isLoading: viewLoading } = useQuery({
    queryKey: ["knowledge-document", viewDoc?.id],
    queryFn: () => (viewDoc?.id ? api.knowledge.getDocument(viewDoc.id) : null),
    enabled: !!viewDoc?.id,
  });

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    setUploading(true);
    try {
      const result = await api.knowledge.ingestFile(formData);
      toast({ title: "Document ingested", description: result.message });
      void qc.invalidateQueries({ queryKey: ["knowledge-documents"] });
    } catch (err: any) {
      toast({ title: "Upload failed", description: err?.message ?? "Unknown error", variant: "destructive" });
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const docs: any[] = data?.data ?? [];
  const filtered = searchQuery
    ? docs.filter((d) =>
        (d.title ?? "").toLowerCase().includes(searchQuery.toLowerCase()) ||
        (d.document_type ?? "").toLowerCase().includes(searchQuery.toLowerCase())
      )
    : docs;

  const kpis = {
    total: docs.length,
    generated: docs.filter((d) => d.source === "generated").length,
    ingested: docs.filter((d) => d.source !== "generated").length,
  };

  return (
    <div className="space-y-4">
      <KpiStrip
        items={[
          { label: "Total Documents", value: kpis.total },
          { label: "Generated", value: kpis.generated },
          { label: "Manually Ingested", value: kpis.ingested },
        ]}
      />

      {/* Toolbar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <FilterBar
          search={{ value: searchQuery, onChange: setSearchQuery, placeholder: "Search documents…" }}
          selects={[
            {
              label: "Type",
              value: docTypeFilter,
              onChange: setDocTypeFilter,
              placeholder: "All Types",
              options: DOC_TYPE_FILTERS.filter((f) => f.value).map((f) => ({ value: f.value, label: f.label })),
            },
          ]}
        />
        <div className="flex items-center gap-2 shrink-0">
          <Button size="sm" variant="outline" onClick={() => void refetch()}>
            <RefreshCw className="h-3.5 w-3.5 mr-1" /> Refresh
          </Button>
          {canUpload && (
            <>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.txt,.csv,.md"
                className="hidden"
                onChange={handleUpload}
              />
              <Button
                size="sm"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
              >
                {uploading ? (
                  <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                ) : (
                  <Upload className="h-3.5 w-3.5 mr-1" />
                )}
                Ingest Document
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            <Database className="inline h-4 w-4 mr-2 text-primary" />
            Knowledge Base Documents
          </CardTitle>
          <CardDescription>Generated reports and manually ingested documents</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin mr-2" /> Loading documents…
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-2">
              <Database className="h-10 w-10 opacity-30" />
              <p className="text-sm">
                {searchQuery ? "No documents match your search." : "No documents in the knowledge base yet."}
              </p>
              {canUpload && !searchQuery && (
                <p className="text-xs">Use the &ldquo;Ingest Document&rdquo; button to add documents.</p>
              )}
            </div>
          ) : isMobile ? (
            <div className="space-y-3 p-4">
              {filtered.map((doc) => (
                <div key={doc.id} className="rounded-lg border border-border/60 bg-muted/20 p-3 space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-medium text-sm leading-5">{doc.title ?? "—"}</p>
                    <p className="text-xs text-muted-foreground shrink-0">{formatDate(doc.created_at)}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <span className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs bg-blue-500/15 text-blue-300 border-blue-500/30">
                      {(doc.document_type ?? "—").replace(/_/g, " ")}
                    </span>
                    <span className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs uppercase text-muted-foreground border-border/60">
                      {doc.format ?? "—"}
                    </span>
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs",
                        doc.source === "generated"
                          ? "bg-purple-500/15 text-purple-300 border-purple-500/30"
                          : "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                      )}
                    >
                      {doc.source ?? "—"}
                    </span>
                  </div>
                  <div className="flex items-center justify-end gap-2">
                    {doc.download_url && (
                      <Button size="sm" variant="ghost" asChild>
                        <a href={doc.download_url} target="_blank" rel="noreferrer">
                          <Download className="h-3.5 w-3.5" />
                        </a>
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" onClick={() => setViewDoc(doc)}>
                      <Eye className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="sticky left-0 z-10 min-w-[220px] bg-muted/90">Title</TableHead>
                    <TableHead className="min-w-[120px]">Type</TableHead>
                    <TableHead className="min-w-[100px]">Format</TableHead>
                    <TableHead className="min-w-[110px]">Source</TableHead>
                    <TableHead className="min-w-[110px]">Date</TableHead>
                    <TableHead className="text-right min-w-[90px]">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((doc) => (
                    <TableRow key={doc.id}>
                      <TableCell className="sticky left-0 z-10 bg-background font-medium max-w-xs truncate" title={doc.title}>
                        {doc.title ?? "—"}
                      </TableCell>
                      <TableCell>
                        <span className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs bg-blue-500/15 text-blue-300 border-blue-500/30">
                          {(doc.document_type ?? "—").replace(/_/g, " ")}
                        </span>
                      </TableCell>
                      <TableCell className="uppercase text-xs text-muted-foreground">{doc.format ?? "—"}</TableCell>
                      <TableCell>
                        <span
                          className={cn(
                            "inline-flex items-center rounded-full border px-2 py-0.5 text-xs",
                            doc.source === "generated"
                              ? "bg-purple-500/15 text-purple-300 border-purple-500/30"
                              : "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                          )}
                        >
                          {doc.source ?? "—"}
                        </span>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">{formatDate(doc.created_at)}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          {doc.download_url && (
                            <Button size="sm" variant="ghost" asChild>
                              <a href={doc.download_url} target="_blank" rel="noreferrer">
                                <Download className="h-3.5 w-3.5" />
                              </a>
                            </Button>
                          )}
                          <Button size="sm" variant="ghost" onClick={() => setViewDoc(doc)}>
                            <Eye className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Document Viewer Dialog */}
      <Dialog open={!!viewDoc} onOpenChange={(open) => !open && setViewDoc(null)}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{viewDoc?.title ?? "Document"}</DialogTitle>
            <DialogDescription>
              {(viewDoc?.document_type ?? "").replace(/_/g, " ")} ·{" "}
              {formatDate(viewDoc?.created_at)}
            </DialogDescription>
          </DialogHeader>
          {viewLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : viewData ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-muted-foreground text-xs mb-0.5">Source</p>
                  <p className="font-medium capitalize">{viewData.source}</p>
                </div>
                <div>
                  <p className="text-muted-foreground text-xs mb-0.5">Format</p>
                  <p className="font-medium uppercase">{viewData.format}</p>
                </div>
                {viewData.department && (
                  <div>
                    <p className="text-muted-foreground text-xs mb-0.5">Department</p>
                    <p className="font-medium">{viewData.department}</p>
                  </div>
                )}
                {viewData.generated_by && (
                  <div>
                    <p className="text-muted-foreground text-xs mb-0.5">Generated by</p>
                    <p className="font-medium">{viewData.generated_by}</p>
                  </div>
                )}
              </div>
              {(viewData.chunks?.length ?? 0) > 0 && (
                <div className="space-y-2">
                  <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
                    Content Preview ({viewData.chunks.length} excerpt{viewData.chunks.length !== 1 ? "s" : ""})
                  </p>
                  {viewData.chunks.map((c: any, i: number) => (
                    <div key={i} className="rounded-md bg-muted/40 border border-border p-3 text-sm whitespace-pre-wrap">
                      {c.content}
                    </div>
                  ))}
                </div>
              )}
              {viewData.download_url && (
                <DialogFooter>
                  <Button asChild>
                    <a href={viewData.download_url} target="_blank" rel="noreferrer">
                      <Download className="h-4 w-4 mr-2" /> Download
                    </a>
                  </Button>
                </DialogFooter>
              )}
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">Could not load document.</p>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ─── Overview Tab ─────────────────────────────────────────────────────────────

function OverviewTab() {
  const { data: status, isLoading } = useQuery({
    queryKey: ["compliance-status"],
    queryFn: () => api.compliance.status(),
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const score = status?.overall_compliance_score ?? status?.compliance_score ?? 0;
  const scoreColor = score >= 80 ? "text-green-400" : score >= 60 ? "text-yellow-400" : "text-red-400";
  const scoreGradient =
    score >= 80
      ? "from-green-500/20 to-emerald-500/10"
      : score >= 60
      ? "from-yellow-500/20 to-amber-500/10"
      : "from-red-500/20 to-rose-500/10";

  const overdueAudits = status?.overdue_audits ?? 0;
  const openDeviations = status?.open_deviations ?? 0;
  const overdueMaintenance = status?.overdue_maintenance ?? 0;
  const activeRecalls = status?.active_recalls ?? 0;
  const missedActivities = status?.missed_activities ?? 0;

  // The backend only ever returns the single reduced score, never a
  // breakdown — but the breakdown is trivially derivable from the response's
  // own real counts, using the exact same weights compliance_status() uses
  // internally (overdue_audits*8, open_deviations*3, overdue_maintenance*4,
  // missed_activities*5). No fabrication, no backend change needed.
  const deductions = [
    { label: "Overdue Audits", points: overdueAudits * 8 },
    { label: "Open Deviations", points: openDeviations * 3 },
    { label: "Overdue Maintenance", points: overdueMaintenance * 4 },
    { label: "Missed Activities", points: missedActivities * 5 },
  ].filter((d) => d.points > 0);

  return (
    <motion.div className="space-y-6" {...motionTransitions}>
      {/* Score gauge card */}
      <Card className={cn("bg-gradient-to-br", scoreGradient, "border-sidebar-border/60")}>
        <CardHeader className="pb-2">
          <CardDescription>Overall Compliance Score</CardDescription>
        </CardHeader>
        <CardContent>
          <p className={cn("text-6xl font-bold tabular-nums", scoreColor)}>{score}<span className="text-2xl opacity-60">%</span></p>
          <p className="mt-1 text-xs text-muted-foreground">
            {score >= 80 ? "Good standing" : score >= 60 ? "Needs attention" : "Critical — immediate action required"}
          </p>
          {score >= 80 ? (
            <TrendingUp className="mt-2 h-5 w-5 text-green-400" />
          ) : (
            <TrendingDown className="mt-2 h-5 w-5 text-red-400" />
          )}
        </CardContent>
      </Card>

      <KpiStrip
        items={[
          { label: "Audits Overdue", value: overdueAudits, icon: ClipboardList, tone: overdueAudits > 0 ? "warning" : "default" },
          { label: "Open Deviations", value: openDeviations, icon: AlertTriangle, tone: openDeviations > 0 ? "warning" : "default" },
          { label: "Maintenance Overdue", value: overdueMaintenance, icon: Wrench, tone: overdueMaintenance > 0 ? "warning" : "default" },
          { label: "Active Recalls", value: activeRecalls, icon: PackageX, tone: activeRecalls > 0 ? "danger" : "default" },
          { label: "Missed Activities", value: missedActivities, icon: Activity, tone: missedActivities > 0 ? "danger" : "default" },
        ]}
      />

      {/* Deductions breakdown */}
      {deductions.length > 0 && (
        <Card className="border-sidebar-border/60">
          <CardHeader>
            <CardTitle className="text-base">Score Deductions</CardTitle>
            <CardDescription>Items reducing your compliance score</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {deductions.map((d) => (
                <div key={d.label} className="flex items-center justify-between rounded-lg bg-muted/30 px-3 py-2 text-sm">
                  <span className="text-muted-foreground">{d.label}</span>
                  <span className="font-semibold text-red-400">-{d.points} pts</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </motion.div>
  );
}

// ─── Audits Tab ───────────────────────────────────────────────────────────────

const AUDIT_STATUSES = ["scheduled", "in_progress", "completed", "overdue", "skipped"];

function AuditsTab() {
  const isMobile = useIsMobile();
  const { toast } = useToast();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [department, setDepartment] = useState("");
  const [status, setStatus] = useState("");
  const [completeDialog, setCompleteDialog] = useState<any>(null);
  const [completeForm, setCompleteForm] = useState({ findings: "", recommendations: "" });
  const [generateDialog, setGenerateDialog] = useState<any>(null);
  const [generateForm, setGenerateForm] = useState({
    auditor_name: "",
    summary: "",
    findings: [""] as string[],
    observations: [""] as string[],
    recommendations: [""] as string[],
    score: "",
  });

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["compliance-audits"],
    queryFn: () => api.compliance.audits(),
    staleTime: 60_000,
  });

  const startMutation = useMutation({
    mutationFn: (auditId: string) => api.compliance.startAudit(auditId),
    onSuccess: () => {
      toast({ title: "Audit started" });
      void qc.invalidateQueries({ queryKey: ["compliance-audits"] });
      void qc.invalidateQueries({ queryKey: ["compliance-status"] });
    },
    onError: (e: any) => toast({ title: "Error", description: e.message, variant: "destructive" }),
  });

  const completeMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: any }) =>
      api.compliance.completeAudit(id, payload),
    onSuccess: () => {
      toast({ title: "Audit completed", description: "Report generation queued." });
      setCompleteDialog(null);
      void qc.invalidateQueries({ queryKey: ["compliance-audits"] });
      void qc.invalidateQueries({ queryKey: ["compliance-status"] });
    },
    onError: (e: any) => toast({ title: "Error", description: e.message, variant: "destructive" }),
  });

  const generateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: any }) =>
      api.compliance.generateAuditReport(id, payload),
    onSuccess: () => {
      toast({ title: "Report generation queued", description: "PDF will appear in the Documents tab shortly." });
      setGenerateDialog(null);
      void qc.invalidateQueries({ queryKey: ["compliance-audits"] });
      // Background: enrich audit intelligence via ReportGenerationAgent
      void api.reports.generate({ report_type: "audit", intent_text: "generate audit report" }).catch(() => {});
    },
    onError: (e: any) => toast({ title: "Error", description: e.message, variant: "destructive" }),
  });

  const allAudits: any[] = data?.audits ?? [];

  const departments = Array.from(new Set(allAudits.map((a) => a.department).filter(Boolean)));

  const audits = allAudits.filter((a) => {
    const q = search.trim().toLowerCase();
    const matchQ = !q || (a.audit_type ?? "").toLowerCase().includes(q);
    const matchDept = !department || a.department === department;
    const matchStatus = !status || a.status === status;
    return matchQ && matchDept && matchStatus;
  });

  const kpis = {
    total: allAudits.length,
    overdue: allAudits.filter((a) => a.status === "overdue").length,
    inProgress: allAudits.filter((a) => a.status === "in_progress").length,
    completed: allAudits.filter((a) => a.status === "completed").length,
  };

  return (
    <motion.div className="space-y-4" {...motionTransitions}>
      <KpiStrip
        items={[
          { label: "Total Audits", value: kpis.total },
          { label: "Overdue", value: kpis.overdue, tone: kpis.overdue > 0 ? "danger" : "default" },
          { label: "In Progress", value: kpis.inProgress, tone: "warning" },
          { label: "Completed", value: kpis.completed, tone: "success" },
        ]}
      />

      <div className="flex items-center justify-between gap-3">
        <FilterBar
          search={{ value: search, onChange: setSearch, placeholder: "Search audit type..." }}
          selects={[
            {
              label: "Department",
              value: department,
              onChange: setDepartment,
              placeholder: "All Departments",
              options: departments.map((d) => ({ value: d, label: d })),
            },
            {
              label: "Status",
              value: status,
              onChange: setStatus,
              placeholder: "All Statuses",
              options: AUDIT_STATUSES.map((s) => ({ value: s, label: s.replace(/_/g, " ") })),
            },
          ]}
        />
        <Button variant="outline" size="sm" onClick={() => refetch()} className="shrink-0">
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Refresh
        </Button>
      </div>

      {isLoading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <Card className="border-sidebar-border/60">
          {isMobile ? (
            <div className="space-y-3 p-4">
              {audits.length === 0 ? (
                <p className="text-center text-muted-foreground py-8">No audits found</p>
              ) : (
                audits.map((a: any) => (
                  <div key={a.id} className="rounded-lg border border-border/60 bg-muted/20 p-3 space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-medium text-sm leading-5">{a.audit_type}</p>
                      {statusBadge(a.status)}
                    </div>
                    <div className="flex flex-wrap gap-2 text-xs">
                      <span className="text-muted-foreground">{a.department}</span>
                      <span className="text-muted-foreground">•</span>
                      <span className="text-muted-foreground">{a.month_due ? `Month ${a.month_due}/${a.year}` : "—"}</span>
                    </div>
                    <div>{severityBadge(a.risk_level ?? "low")}</div>
                    <div className="flex flex-wrap justify-end gap-2 pt-1">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setGenerateDialog(a);
                          setGenerateForm({ auditor_name: "", summary: "", findings: [""], observations: [""], recommendations: [""], score: "" });
                        }}
                      >
                        <FileText className="mr-1.5 h-3.5 w-3.5" /> Generate Report
                      </Button>
                      {a.status === "scheduled" && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => startMutation.mutate(a.id)}
                          disabled={startMutation.isPending}
                        >
                          {startMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Start"}
                        </Button>
                      )}
                      {a.status === "in_progress" && (
                        <Button
                          size="sm"
                          onClick={() => { setCompleteDialog(a); setCompleteForm({ findings: "", recommendations: "" }); }}
                        >
                          <CheckCircle className="mr-1.5 h-3.5 w-3.5" /> Complete
                        </Button>
                      )}
                      {a.report_url && (
                        <Button size="sm" variant="ghost" asChild>
                          <a href={a.report_url} target="_blank" rel="noopener noreferrer">
                            <Download className="h-3.5 w-3.5" />
                          </a>
                        </Button>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="sticky left-0 z-10 min-w-[220px] bg-muted/90">Audit Type</TableHead>
                    <TableHead className="min-w-[120px]">Department</TableHead>
                    <TableHead className="min-w-[120px]">Month Due</TableHead>
                    <TableHead className="min-w-[100px]">Risk Level</TableHead>
                    <TableHead className="min-w-[100px]">Status</TableHead>
                    <TableHead className="text-right min-w-[220px]">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {audits.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={6} className="text-center text-muted-foreground py-10">
                        No audits found
                      </TableCell>
                    </TableRow>
                  ) : (
                    audits.map((a: any) => (
                      <TableRow key={a.id}>
                        <TableCell className="sticky left-0 z-10 bg-background font-medium">{a.audit_type}</TableCell>
                        <TableCell>{a.department}</TableCell>
                        <TableCell>{a.month_due ? `${a.month_due}/${a.year}` : "—"}</TableCell>
                        <TableCell>{severityBadge(a.risk_level ?? "low")}</TableCell>
                        <TableCell>{statusBadge(a.status)}</TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                setGenerateDialog(a);
                                setGenerateForm({ auditor_name: "", summary: "", findings: [""], observations: [""], recommendations: [""], score: "" });
                              }}
                            >
                              <FileText className="mr-1.5 h-3.5 w-3.5" /> Generate Report
                            </Button>
                            {a.status === "scheduled" && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => startMutation.mutate(a.id)}
                                disabled={startMutation.isPending}
                              >
                                {startMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Start"}
                              </Button>
                            )}
                            {a.status === "in_progress" && (
                              <Button
                                size="sm"
                                onClick={() => { setCompleteDialog(a); setCompleteForm({ findings: "", recommendations: "" }); }}
                              >
                                <CheckCircle className="mr-1.5 h-3.5 w-3.5" /> Complete
                              </Button>
                            )}
                            {a.report_url && (
                              <Button size="sm" variant="ghost" asChild>
                                <a href={a.report_url} target="_blank" rel="noopener noreferrer">
                                  <Download className="h-3.5 w-3.5" />
                                </a>
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </Card>
      )}

      {/* Complete audit dialog */}
      <Dialog open={!!completeDialog} onOpenChange={(o) => !o && setCompleteDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Complete Audit</DialogTitle>
            <DialogDescription>{completeDialog?.audit_type}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label>Findings</Label>
              <Textarea
                rows={3}
                placeholder="Key findings during this audit, one per line..."
                value={completeForm.findings}
                onChange={(e) => setCompleteForm((f) => ({ ...f, findings: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Recommendations</Label>
              <Textarea
                rows={3}
                placeholder="Recommendations for improvement, one per line..."
                value={completeForm.recommendations}
                onChange={(e) => setCompleteForm((f) => ({ ...f, recommendations: e.target.value }))}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCompleteDialog(null)}>Cancel</Button>
            <Button
              disabled={completeMutation.isPending}
              onClick={() =>
                completeMutation.mutate({
                  id: completeDialog.id,
                  payload: {
                    findings: completeForm.findings.split("\n").map((s) => s.trim()).filter(Boolean),
                    recommendations: completeForm.recommendations.split("\n").map((s) => s.trim()).filter(Boolean),
                  },
                })
              }
            >
              {completeMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle className="mr-2 h-4 w-4" />}
              Complete Audit
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Generate Audit Report sheet ── */}
      <DetailSheet
        open={!!generateDialog}
        onOpenChange={(o) => !o && setGenerateDialog(null)}
        title="Generate Audit Report"
        description={`${generateDialog?.audit_type ?? ""} — ${generateDialog?.department ?? ""}${generateDialog?.month_due ? ` · Month ${generateDialog.month_due}/${generateDialog?.year}` : ""}`}
        icon={FileText}
        footer={
          <Button
            className="w-full"
            disabled={generateMutation.isPending}
            onClick={() => {
              const payload: any = {};
              if (generateForm.auditor_name) payload.auditor_name = generateForm.auditor_name;
              if (generateForm.summary)      payload.summary      = generateForm.summary;
              const findings = generateForm.findings.filter(Boolean);
              if (findings.length)           payload.findings     = findings;
              const obs = generateForm.observations.filter(Boolean);
              if (obs.length)                payload.observations = obs;
              const recs = generateForm.recommendations.filter(Boolean);
              if (recs.length)               payload.recommendations = recs;
              if (generateForm.score)        payload.score        = Number(generateForm.score);
              generateMutation.mutate({ id: generateDialog.id, payload });
            }}
          >
            {generateMutation.isPending
              ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              : <FileText className="mr-2 h-4 w-4" />}
            Generate Report
          </Button>
        }
      >
          {/* Pre-filled read-only info strip */}
          <div className="grid grid-cols-3 gap-3 rounded-lg border border-sidebar-border/50 bg-muted/20 p-3 text-sm">
            <div><span className="text-muted-foreground text-xs">Risk Level</span><br /><span className="font-medium capitalize">{generateDialog?.risk_level ?? "—"}</span></div>
            <div><span className="text-muted-foreground text-xs">Department</span><br /><span className="font-medium">{generateDialog?.department ?? "—"}</span></div>
            <div><span className="text-muted-foreground text-xs">Frequency</span><br /><span className="font-medium capitalize">{generateDialog?.frequency ?? "—"}</span></div>
          </div>

          <div className="space-y-5 py-1">
            <div className="space-y-1.5">
              <Label>Auditor Name</Label>
              <Input
                placeholder="Name of the auditor conducting this audit"
                value={generateForm.auditor_name}
                onChange={(e) => setGenerateForm((f) => ({ ...f, auditor_name: e.target.value }))}
              />
            </div>

            <div className="space-y-1.5">
              <Label>Executive Summary</Label>
              <Textarea
                rows={3}
                placeholder="Summarise the scope and overall outcome of the audit…"
                value={generateForm.summary}
                onChange={(e) => setGenerateForm((f) => ({ ...f, summary: e.target.value }))}
              />
            </div>

            {/* Dynamic findings */}
            <div className="space-y-2">
              <Label>Findings</Label>
              {generateForm.findings.map((item, i) => (
                <div key={i} className="flex gap-2">
                  <Input
                    placeholder={`Finding ${i + 1}`}
                    value={item}
                    onChange={(e) => {
                      const next = [...generateForm.findings];
                      next[i] = e.target.value;
                      setGenerateForm((f) => ({ ...f, findings: next }));
                    }}
                  />
                  {generateForm.findings.length > 1 && (
                    <Button size="icon" variant="ghost" onClick={() =>
                      setGenerateForm((f) => ({ ...f, findings: f.findings.filter((_, j) => j !== i) }))
                    }>
                      <XCircle className="h-4 w-4 text-muted-foreground" />
                    </Button>
                  )}
                </div>
              ))}
              <Button size="sm" variant="outline" onClick={() =>
                setGenerateForm((f) => ({ ...f, findings: [...f.findings, ""] }))
              }>
                <Plus className="mr-1.5 h-3.5 w-3.5" /> Add Finding
              </Button>
            </div>

            {/* Dynamic observations */}
            <div className="space-y-2">
              <Label>Observations</Label>
              {generateForm.observations.map((item, i) => (
                <div key={i} className="flex gap-2">
                  <Input
                    placeholder={`Observation ${i + 1}`}
                    value={item}
                    onChange={(e) => {
                      const next = [...generateForm.observations];
                      next[i] = e.target.value;
                      setGenerateForm((f) => ({ ...f, observations: next }));
                    }}
                  />
                  {generateForm.observations.length > 1 && (
                    <Button size="icon" variant="ghost" onClick={() =>
                      setGenerateForm((f) => ({ ...f, observations: f.observations.filter((_, j) => j !== i) }))
                    }>
                      <XCircle className="h-4 w-4 text-muted-foreground" />
                    </Button>
                  )}
                </div>
              ))}
              <Button size="sm" variant="outline" onClick={() =>
                setGenerateForm((f) => ({ ...f, observations: [...f.observations, ""] }))
              }>
                <Plus className="mr-1.5 h-3.5 w-3.5" /> Add Observation
              </Button>
            </div>

            {/* Dynamic recommendations */}
            <div className="space-y-2">
              <Label>Recommendations</Label>
              {generateForm.recommendations.map((item, i) => (
                <div key={i} className="flex gap-2">
                  <Input
                    placeholder={`Recommendation ${i + 1}`}
                    value={item}
                    onChange={(e) => {
                      const next = [...generateForm.recommendations];
                      next[i] = e.target.value;
                      setGenerateForm((f) => ({ ...f, recommendations: next }));
                    }}
                  />
                  {generateForm.recommendations.length > 1 && (
                    <Button size="icon" variant="ghost" onClick={() =>
                      setGenerateForm((f) => ({ ...f, recommendations: f.recommendations.filter((_, j) => j !== i) }))
                    }>
                      <XCircle className="h-4 w-4 text-muted-foreground" />
                    </Button>
                  )}
                </div>
              ))}
              <Button size="sm" variant="outline" onClick={() =>
                setGenerateForm((f) => ({ ...f, recommendations: [...f.recommendations, ""] }))
              }>
                <Plus className="mr-1.5 h-3.5 w-3.5" /> Add Recommendation
              </Button>
            </div>

            <div className="space-y-1.5">
              <Label>Compliance Score (0–100, optional)</Label>
              <Input
                type="number"
                min={0}
                max={100}
                placeholder="e.g. 88"
                value={generateForm.score}
                onChange={(e) => setGenerateForm((f) => ({ ...f, score: e.target.value }))}
              />
            </div>
          </div>
      </DetailSheet>
    </motion.div>
  );
}

// ─── Deviations Tab — consolidated onto QualityControl.tsx's CapaTab ─────────
// DeviationsTab and CapaTab were two independent, parallel UIs over the same
// deviation_reports table via two different routers (/compliance/deviations
// vs /qc/deviations). CapaTab's field names correctly match the DB schema
// and its role check isn't broken; DeviationsTab was 100% non-functional in
// every direction (couldn't list — a response-shape bug; couldn't create —
// its form's field names don't exist anywhere on the real model). Resolved
// the same way as the AR Aging consolidation: this tab is now a KpiStrip +
// link-through to the real page. The one thing this tab had that CapaTab
// didn't — PDF "Generate Report" export — was ported into CapaTab's Detail
// Workspace as a new action instead of being dropped. See
// ACE-Workspace-Standard.md §9.12.
const SEVERITY_OPTIONS = ["critical", "major", "minor", "low"];

function DeviationsTab() {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ["qc-deviations-summary"],
    queryFn: () => api.qc.listDeviations(),
  });
  const deviations: any[] = data?.deviations ?? (Array.isArray(data) ? data : []);

  const kpis = {
    total: deviations.length,
    open: deviations.filter((d) => d.status === "open").length,
    escalated: deviations.filter((d) => d.status === "escalated").length,
    closed: deviations.filter((d) => d.status === "closed").length,
  };

  return (
    <motion.div className="space-y-4" {...motionTransitions}>
      <Card className="border-sidebar-border/60">
        <CardHeader>
          <CardTitle className="text-base">Deviations &amp; CAPA</CardTitle>
          <CardDescription>
            Deviation reporting and CAPA tracking live on the Quality Control page — this is a summary.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {isLoading ? (
            <div className="flex h-24 items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <KpiStrip
              items={[
                { label: "Total Deviations", value: kpis.total },
                { label: "Open", value: kpis.open, tone: kpis.open > 0 ? "warning" : "default" },
                { label: "Escalated", value: kpis.escalated, tone: kpis.escalated > 0 ? "danger" : "default" },
                { label: "Closed", value: kpis.closed, tone: "success" },
              ]}
            />
          )}
          <Button onClick={() => navigate("/quality-control")} className="gap-2">
            View Full CAPA &amp; Deviations <FileText className="w-4 h-4" />
          </Button>
        </CardContent>
      </Card>
    </motion.div>
  );
}

// ─── Maintenance Tab ──────────────────────────────────────────────────────────

const MAINTENANCE_STATUSES = ["scheduled", "completed", "overdue", "cancelled"];

function MaintenanceTab() {
  const isMobile = useIsMobile();
  const { toast } = useToast();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [completeDialog, setCompleteDialog] = useState<any>(null);
  const [completeForm, setCompleteForm] = useState({ performed_by: "", completion_notes: "", next_maintenance_date: "" });
  const [certDialog, setCertDialog] = useState<any>(null);
  const [certForm, setCertForm] = useState({
    performed_by: "",
    maintenance_type: "preventive",
    completion_notes: "",
    next_maintenance_date: "",
  });

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["compliance-maintenance", status],
    queryFn: () => api.compliance.maintenance(status || undefined),
    staleTime: 60_000,
  });

  const completeMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: any }) =>
      api.compliance.completeMaintenance(id, payload),
    onSuccess: () => {
      toast({ title: "Maintenance task completed" });
      setCompleteDialog(null);
      void qc.invalidateQueries({ queryKey: ["compliance-maintenance"] });
      void qc.invalidateQueries({ queryKey: ["compliance-status"] });
    },
    onError: (e: any) => toast({ title: "Error", description: e.message, variant: "destructive" }),
  });

  const certMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: any }) =>
      api.compliance.generateMaintenanceCertificate(id, payload),
    onSuccess: () => {
      toast({ title: "Certificate queued", description: "PDF will appear in the Documents tab shortly." });
      setCertDialog(null);
      // Background: enrich maintenance intelligence via ReportGenerationAgent
      void api.reports.generate({ report_type: "maintenance", intent_text: "generate maintenance report" }).catch(() => {});
    },
    onError: (e: any) => toast({ title: "Error", description: e.message, variant: "destructive" }),
  });

  const allMaintenance: any[] = data?.maintenance ?? [];
  const maintenance = search.trim()
    ? allMaintenance.filter((m) => {
        const q = search.trim().toLowerCase();
        const name = m.equipment_registry?.equipment_name ?? "";
        return name.toLowerCase().includes(q) || (m.maintenance_type ?? "").toLowerCase().includes(q);
      })
    : allMaintenance;

  const kpis = {
    total: allMaintenance.length,
    overdue: allMaintenance.filter((m) => m.status === "overdue").length,
    scheduled: allMaintenance.filter((m) => m.status === "scheduled").length,
    completed: allMaintenance.filter((m) => m.status === "completed").length,
  };

  return (
    <motion.div className="space-y-4" {...motionTransitions}>
      <KpiStrip
        items={[
          { label: "Total Tasks", value: kpis.total },
          { label: "Overdue", value: kpis.overdue, tone: kpis.overdue > 0 ? "danger" : "default" },
          { label: "Scheduled", value: kpis.scheduled, tone: "warning" },
          { label: "Completed", value: kpis.completed, tone: "success" },
        ]}
      />

      <div className="flex items-center justify-between gap-3">
        <FilterBar
          search={{ value: search, onChange: setSearch, placeholder: "Search equipment or type..." }}
          selects={[
            {
              label: "Status",
              value: status,
              onChange: setStatus,
              placeholder: "All Statuses",
              options: MAINTENANCE_STATUSES.map((s) => ({ value: s, label: s })),
            },
          ]}
        />
        <Button variant="outline" size="sm" onClick={() => refetch()} className="shrink-0">
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Refresh
        </Button>
      </div>

      {isLoading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <Card className="border-sidebar-border/60">
          {isMobile ? (
            <div className="space-y-3 p-3">
              {maintenance.length === 0 ? (
                <p className="py-10 text-center text-muted-foreground">No maintenance tasks found</p>
              ) : (
                maintenance.map((m: any) => (
                  <div key={m.id} className="rounded-lg border bg-card p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-medium leading-tight">{m.equipment_registry?.equipment_name ?? m.equipment_id}</p>
                        <p className="mt-1 text-xs text-muted-foreground">{m.equipment_registry?.location ?? "—"}</p>
                      </div>
                      {statusBadge(m.status)}
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className="text-xs">{m.maintenance_type}</Badge>
                      <span className="text-xs text-muted-foreground">Due: {formatDate(m.next_maintenance_date)}</span>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {(m.status === "scheduled" || m.status === "overdue") && (
                        <Button
                          size="sm"
                          onClick={() => {
                            setCompleteDialog(m);
                            setCompleteForm({ performed_by: "", completion_notes: "", next_maintenance_date: "" });
                          }}
                        >
                          <CheckCircle className="mr-1.5 h-3.5 w-3.5" /> Complete
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setCertDialog(m);
                          setCertForm({ performed_by: "", maintenance_type: m.maintenance_type ?? "preventive", completion_notes: "", next_maintenance_date: "" });
                        }}
                      >
                        <FileText className="mr-1.5 h-3.5 w-3.5" /> Certificate
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="sticky left-0 z-10 min-w-[200px] bg-muted/90">Equipment</TableHead>
                    <TableHead className="min-w-[160px]">Location</TableHead>
                    <TableHead className="min-w-[110px]">Type</TableHead>
                    <TableHead className="min-w-[120px]">Due Date</TableHead>
                    <TableHead className="min-w-[100px]">Status</TableHead>
                    <TableHead className="min-w-[220px] text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {maintenance.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={6} className="py-10 text-center text-muted-foreground">
                        No maintenance tasks found
                      </TableCell>
                    </TableRow>
                  ) : (
                    maintenance.map((m: any) => (
                      <TableRow key={m.id}>
                        <TableCell className="sticky left-0 z-10 bg-background font-medium">{m.equipment_registry?.equipment_name ?? m.equipment_id}</TableCell>
                        <TableCell className="text-sm text-muted-foreground">{m.equipment_registry?.location ?? "—"}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className="text-xs">{m.maintenance_type}</Badge>
                        </TableCell>
                        <TableCell className="text-sm">{formatDate(m.next_maintenance_date)}</TableCell>
                        <TableCell>{statusBadge(m.status)}</TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-2">
                            {(m.status === "scheduled" || m.status === "overdue") && (
                              <Button
                                size="sm"
                                onClick={() => {
                                  setCompleteDialog(m);
                                  setCompleteForm({ performed_by: "", completion_notes: "", next_maintenance_date: "" });
                                }}
                              >
                                <CheckCircle className="mr-1.5 h-3.5 w-3.5" /> Complete
                              </Button>
                            )}
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                setCertDialog(m);
                                setCertForm({ performed_by: "", maintenance_type: m.maintenance_type ?? "preventive", completion_notes: "", next_maintenance_date: "" });
                              }}
                            >
                              <FileText className="mr-1.5 h-3.5 w-3.5" /> Certificate
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </Card>
      )}

      <Dialog open={!!completeDialog} onOpenChange={(o) => !o && setCompleteDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Record Maintenance Completion</DialogTitle>
            <DialogDescription>
              {completeDialog?.equipment_registry?.equipment_name ?? completeDialog?.equipment_id}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label>Performed By *</Label>
              <Input
                placeholder="Technician name"
                value={completeForm.performed_by}
                onChange={(e) => setCompleteForm((f) => ({ ...f, performed_by: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Notes</Label>
              <Textarea
                rows={3}
                placeholder="Work performed, observations..."
                value={completeForm.completion_notes}
                onChange={(e) => setCompleteForm((f) => ({ ...f, completion_notes: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Next Due Date (optional)</Label>
              <Input
                type="date"
                value={completeForm.next_maintenance_date}
                onChange={(e) => setCompleteForm((f) => ({ ...f, next_maintenance_date: e.target.value }))}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCompleteDialog(null)}>Cancel</Button>
            <Button
              disabled={completeMutation.isPending || !completeForm.performed_by}
              onClick={() =>
                completeMutation.mutate({
                  id: completeDialog.id,
                  payload: {
                    performed_by: completeForm.performed_by,
                    completion_notes: completeForm.completion_notes || undefined,
                    next_maintenance_date: completeForm.next_maintenance_date || undefined,
                  },
                })
              }
            >
              {completeMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle className="mr-2 h-4 w-4" />}
              Mark Complete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Generate Maintenance Certificate sheet ── */}
      <DetailSheet
        open={!!certDialog}
        onOpenChange={(o) => !o && setCertDialog(null)}
        title="Generate Maintenance Certificate"
        description={certDialog?.equipment_registry?.equipment_name ?? certDialog?.equipment_id}
        icon={FileText}
        footer={
          <Button
            className="w-full"
            disabled={certMutation.isPending || !certForm.performed_by}
            onClick={() =>
              certMutation.mutate({
                id: certDialog.id,
                payload: {
                  performed_by: certForm.performed_by,
                  maintenance_type: certForm.maintenance_type,
                  completion_notes: certForm.completion_notes || undefined,
                  next_maintenance_date: certForm.next_maintenance_date || undefined,
                },
              })
            }
          >
            {certMutation.isPending
              ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              : <FileText className="mr-2 h-4 w-4" />}
            Generate Certificate
          </Button>
        }
      >
        <div className="space-y-1.5">
          <Label>Performed By *</Label>
          <Input
            placeholder="Technician / engineer name"
            value={certForm.performed_by}
            onChange={(e) => setCertForm((f) => ({ ...f, performed_by: e.target.value }))}
          />
        </div>
        <div className="space-y-1.5">
          <Label>Maintenance Type</Label>
          <Select
            value={certForm.maintenance_type}
            onValueChange={(v) => setCertForm((f) => ({ ...f, maintenance_type: v }))}
          >
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {["preventive", "calibration", "repair", "inspection"].map((t) => (
                <SelectItem key={t} value={t}>
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>Works Performed / Notes</Label>
          <Textarea
            rows={3}
            placeholder="Describe the maintenance work carried out…"
            value={certForm.completion_notes}
            onChange={(e) => setCertForm((f) => ({ ...f, completion_notes: e.target.value }))}
          />
        </div>
        <div className="space-y-1.5">
          <Label>Next Maintenance Date (optional)</Label>
          <Input
            type="date"
            value={certForm.next_maintenance_date}
            onChange={(e) => setCertForm((f) => ({ ...f, next_maintenance_date: e.target.value }))}
          />
        </div>
      </DetailSheet>
    </motion.div>
  );
}

// ─── Recalls Tab ──────────────────────────────────────────────────────────────

function RecallsTab() {
  const isMobile = useIsMobile();
  const { toast } = useToast();
  const qc = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({
    product_name: "",
    batch_number: "",
    recall_reason: "",
    severity: "major",
    nafdac_notified: false,
  });

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["compliance-recalls"],
    queryFn: () => api.compliance.recalls(),
    staleTime: 60_000,
  });

  const createMutation = useMutation({
    mutationFn: (payload: typeof form) => api.compliance.initiateRecall(payload),
    onSuccess: () => {
      toast({ title: "Recall initiated", description: "Recall documents will be generated shortly." });
      setDialogOpen(false);
      setForm({ product_name: "", batch_number: "", recall_reason: "", severity: "major", nafdac_notified: false });
      void qc.invalidateQueries({ queryKey: ["compliance-recalls"] });
      void qc.invalidateQueries({ queryKey: ["compliance-status"] });
    },
    onError: (e: any) => toast({ title: "Error", description: e.message, variant: "destructive" }),
  });

  const docsMutation = useMutation({
    mutationFn: (id: string) => api.compliance.generateRecallDocuments(id),
    onSuccess: () => {
      toast({ title: "Documents queued", description: "PDF recall pack generation in progress." });
      // Background: enrich recall intelligence via ReportGenerationAgent
      void api.reports.generate({ report_type: "deviation", intent_text: "generate recall and deviation report" }).catch(() => {});
    },
    onError: (e: any) => toast({ title: "Error", description: e.message, variant: "destructive" }),
  });

  const recalls: any[] = data?.recalls ?? [];
  const kpis = {
    total: recalls.length,
    active: recalls.filter((r) => r.status !== "closed").length,
    critical: recalls.filter((r) => r.severity === "critical").length,
    nafdacNotified: recalls.filter((r) => r.nafdac_notified).length,
  };

  return (
    <motion.div className="space-y-4" {...motionTransitions}>
      <KpiStrip
        items={[
          { label: "Total Recalls", value: kpis.total },
          { label: "Active", value: kpis.active, tone: kpis.active > 0 ? "warning" : "default" },
          { label: "Critical Severity", value: kpis.critical, tone: kpis.critical > 0 ? "danger" : "default" },
          { label: "NAFDAC Notified", value: kpis.nafdacNotified },
        ]}
      />

      <div className="flex items-center justify-end gap-2">
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Refresh
        </Button>
        <Button size="sm" variant="destructive" onClick={() => setDialogOpen(true)}>
          <PackageX className="mr-1.5 h-3.5 w-3.5" /> Initiate Recall
        </Button>
      </div>

      <DetailSheet
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="Initiate Product Recall"
        description="This action creates a formal recall record and notifies relevant teams."
        icon={AlertTriangle}
        footer={
          <Button
            variant="destructive"
            className="w-full"
            disabled={createMutation.isPending || !form.product_name || !form.batch_number || !form.recall_reason}
            onClick={() => createMutation.mutate(form)}
          >
            {createMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <PackageX className="mr-2 h-4 w-4" />}
            Initiate Recall
          </Button>
        }
      >
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <Label>Product Name *</Label>
                    <Input placeholder="Product name" value={form.product_name} onChange={(e) => setForm((f) => ({ ...f, product_name: e.target.value }))} />
                  </div>
                  <div className="space-y-1.5">
                    <Label>Batch Number *</Label>
                    <Input placeholder="e.g. BATCH-2026-001" value={form.batch_number} onChange={(e) => setForm((f) => ({ ...f, batch_number: e.target.value }))} />
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label>Severity *</Label>
                  <Select value={form.severity} onValueChange={(v) => setForm((f) => ({ ...f, severity: v }))}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {SEVERITY_OPTIONS.map((s) => (
                        <SelectItem key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label>Recall Reason *</Label>
                  <Textarea
                    rows={3}
                    placeholder="Describe the reason for the recall..."
                    value={form.recall_reason}
                    onChange={(e) => setForm((f) => ({ ...f, recall_reason: e.target.value }))}
                  />
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="nafdac"
                    checked={form.nafdac_notified}
                    onChange={(e) => setForm((f) => ({ ...f, nafdac_notified: e.target.checked }))}
                    className="rounded border"
                  />
                  <Label htmlFor="nafdac" className="cursor-pointer">NAFDAC has been notified</Label>
                </div>
      </DetailSheet>

      {isLoading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <Card className="border-sidebar-border/60">
          {isMobile ? (
            <div className="space-y-3 p-3">
              {recalls.length === 0 ? (
                <p className="py-10 text-center text-muted-foreground">No recall records</p>
              ) : (
                recalls.map((r: any) => (
                  <div key={r.id} className="rounded-lg border bg-card p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-medium leading-tight">{r.product_name}</p>
                        <p className="mt-1 font-mono text-[11px] text-muted-foreground">{r.recall_id}</p>
                      </div>
                      {statusBadge(r.status)}
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                      {severityBadge(r.severity)}
                      <span className="text-muted-foreground">Batch: {r.batch_number}</span>
                      <span className="text-muted-foreground">Initiated: {formatDate(r.initiation_date ?? r.created_at)}</span>
                    </div>
                    <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
                      NAFDAC: {r.nafdac_notified ? <CheckCircle className="h-4 w-4 text-green-400" /> : <XCircle className="h-4 w-4 text-muted-foreground" />}
                    </div>
                    <div className="mt-3">
                      <Button
                        size="sm"
                        variant="outline"
                        title="Generate recall notice, investigation & distribution trace PDFs"
                        disabled={docsMutation.isPending}
                        onClick={() => docsMutation.mutate(r.id)}
                      >
                        {docsMutation.isPending
                          ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                          : <FileText className="mr-1.5 h-3.5 w-3.5" />}
                        Generate Docs
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="sticky left-0 z-10 min-w-[120px] bg-muted/90">Recall ID</TableHead>
                    <TableHead className="min-w-[180px]">Product</TableHead>
                    <TableHead className="min-w-[120px]">Batch</TableHead>
                    <TableHead className="min-w-[100px]">Severity</TableHead>
                    <TableHead className="min-w-[120px]">Initiated</TableHead>
                    <TableHead className="min-w-[90px]">NAFDAC</TableHead>
                    <TableHead className="min-w-[100px]">Status</TableHead>
                    <TableHead className="min-w-[130px] text-right">Docs</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {recalls.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={8} className="py-10 text-center text-muted-foreground">
                        No recall records
                      </TableCell>
                    </TableRow>
                  ) : (
                    recalls.map((r: any) => (
                      <TableRow key={r.id}>
                        <TableCell className="sticky left-0 z-10 bg-background font-mono text-xs">{r.recall_id}</TableCell>
                        <TableCell className="font-medium">{r.product_name}</TableCell>
                        <TableCell className="text-sm text-muted-foreground">{r.batch_number}</TableCell>
                        <TableCell>{severityBadge(r.severity)}</TableCell>
                        <TableCell className="text-sm">{formatDate(r.initiation_date ?? r.created_at)}</TableCell>
                        <TableCell>
                          {r.nafdac_notified ? (
                            <CheckCircle className="h-4 w-4 text-green-400" />
                          ) : (
                            <XCircle className="h-4 w-4 text-muted-foreground" />
                          )}
                        </TableCell>
                        <TableCell>{statusBadge(r.status)}</TableCell>
                        <TableCell className="text-right">
                          <Button
                            size="sm"
                            variant="outline"
                            title="Generate recall notice, investigation & distribution trace PDFs"
                            disabled={docsMutation.isPending}
                            onClick={() => docsMutation.mutate(r.id)}
                          >
                            {docsMutation.isPending
                              ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                              : <FileText className="mr-1.5 h-3.5 w-3.5" />}
                            Generate Docs
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </Card>
      )}
    </motion.div>
  );
}

// ─── SOP Index Tab ────────────────────────────────────────────────────────────

const SOP_CATEGORIES = ["storage", "qc", "distribution", "warehouse", "equipment", "deviation", "recall", "hr"];

// sop_registry has no sop_code/next_review_date columns -- the real id
// column is sop_id, and "next review" has to be derived from
// last_reviewed_at (or effective_from, if never reviewed) + review_interval_days.
function sopNextReview(s: any): string | null {
  const anchor = s.last_reviewed_at || s.effective_from;
  if (!anchor || !s.review_interval_days) return null;
  const d = new Date(anchor);
  d.setDate(d.getDate() + Number(s.review_interval_days));
  return d.toISOString();
}

function SopTab() {
  const isMobile = useIsMobile();
  const { toast } = useToast();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string>("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["compliance-sop", category],
    queryFn: () => api.compliance.sopList(category || undefined),
    staleTime: 120_000,
  });

  const allSops: any[] = data?.data ?? (Array.isArray(data) ? data : []);
  const sops = search.trim()
    ? allSops.filter((s) => (s.title ?? "").toLowerCase().includes(search.trim().toLowerCase()))
    : allSops;

  const now = Date.now();
  const kpis = {
    total: allSops.length,
    categories: new Set(allSops.map((s) => s.category).filter(Boolean)).size,
    dueForReview: allSops.filter((s) => {
      const next = sopNextReview(s);
      return next ? new Date(next).getTime() <= now : false;
    }).length,
  };

  const handleUpload = useCallback(async () => {
    if (!uploadFile) return;
    const fd = new FormData();
    fd.append("file", uploadFile);
    try {
      setUploading(true);
      await api.compliance.ingestSopDocx(fd);
      toast({ title: "SOP ingested", description: "Document parsed and indexed for RAG search." });
      setUploadFile(null);
      void qc.invalidateQueries({ queryKey: ["compliance-sop"] });
    } catch (e: any) {
      toast({ title: "Upload failed", description: e.message, variant: "destructive" });
    } finally {
      setUploading(false);
    }
  }, [uploadFile, toast, qc]);

  return (
    <motion.div className="space-y-4" {...motionTransitions}>
      <KpiStrip
        items={[
          { label: "Total SOPs", value: kpis.total },
          { label: "Categories", value: kpis.categories },
          { label: "Due for Review", value: kpis.dueForReview, tone: kpis.dueForReview > 0 ? "warning" : "default" },
        ]}
      />

      <div className="flex items-center justify-between gap-3">
        <FilterBar
          search={{ value: search, onChange: setSearch, placeholder: "Search SOP title..." }}
          selects={[
            {
              label: "Category",
              value: category,
              onChange: setCategory,
              placeholder: "All Categories",
              options: SOP_CATEGORIES.map((c) => ({ value: c, label: c.charAt(0).toUpperCase() + c.slice(1) })),
            },
          ]}
        />
        <Button variant="outline" size="sm" onClick={() => refetch()} className="shrink-0">
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Refresh
        </Button>
      </div>

      {/* DOCX upload */}
      <Card className="border-dashed border-sidebar-border/60 bg-muted/10">
        <CardContent className="flex flex-col items-center justify-center gap-3 py-8 text-center">
          <Upload className="h-8 w-8 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">Upload SOP Document (DOCX)</p>
            <p className="text-xs text-muted-foreground">The document will be parsed and indexed for AI-assisted search.</p>
          </div>
          <div className="flex items-center gap-3">
            <Input
              type="file"
              accept=".docx"
              className="max-w-xs"
              onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
            />
            <Button
              size="sm"
              disabled={!uploadFile || uploading}
              onClick={handleUpload}
            >
              {uploading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}
              {uploading ? "Ingesting..." : "Ingest SOP"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* SOP table */}
      {isLoading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <Card className="border-sidebar-border/60">
          {isMobile ? (
            <div className="space-y-3 p-3">
              {sops.length === 0 ? (
                <p className="py-10 text-center text-muted-foreground">No SOPs found</p>
              ) : (
                sops.map((s: any) => (
                  <div key={s.id} className="rounded-lg border bg-card p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-medium leading-tight">{s.title}</p>
                        <p className="mt-1 font-mono text-[11px] text-muted-foreground">{s.sop_id}</p>
                      </div>
                      {statusBadge(s.status ?? "active")}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Badge variant="outline" className="text-xs capitalize">{s.category}</Badge>
                      <span className="text-xs text-muted-foreground">{s.version ?? "v1.0"}</span>
                      <span className="text-xs text-muted-foreground">Next: {formatDate(sopNextReview(s))}</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="sticky left-0 z-10 min-w-[120px] bg-muted/90">SOP Code</TableHead>
                    <TableHead className="min-w-[260px]">Title</TableHead>
                    <TableHead className="min-w-[120px]">Category</TableHead>
                    <TableHead className="min-w-[100px]">Version</TableHead>
                    <TableHead className="min-w-[130px]">Next Review</TableHead>
                    <TableHead className="min-w-[100px]">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sops.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={6} className="py-10 text-center text-muted-foreground">
                        No SOPs found
                      </TableCell>
                    </TableRow>
                  ) : (
                    sops.map((s: any) => (
                      <TableRow key={s.id}>
                        <TableCell className="sticky left-0 z-10 bg-background font-mono text-xs">{s.sop_id}</TableCell>
                        <TableCell className="font-medium">{s.title}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className="text-xs capitalize">{s.category}</Badge>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">{s.version ?? "v1.0"}</TableCell>
                        <TableCell className="text-sm">{formatDate(sopNextReview(s))}</TableCell>
                        <TableCell>{statusBadge(s.status ?? "active")}</TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </Card>
      )}
    </motion.div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function Compliance() {
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        icon={ShieldCheck}
        title="Compliance & QMS"
        subtitle="Quality Management System — Audits, Deviations, Maintenance, Recalls & SOP Index"
      />

      {/* Tabs */}
      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList className="grid w-full grid-cols-7">
          <TabsTrigger value="overview" className="gap-1.5">
            <ShieldCheck className="h-3.5 w-3.5" /> Overview
          </TabsTrigger>
          <TabsTrigger value="audits" className="gap-1.5">
            <ClipboardList className="h-3.5 w-3.5" /> Audits
          </TabsTrigger>
          <TabsTrigger value="deviations" className="gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5" /> Deviations
          </TabsTrigger>
          <TabsTrigger value="maintenance" className="gap-1.5">
            <Wrench className="h-3.5 w-3.5" /> Maintenance
          </TabsTrigger>
          <TabsTrigger value="recalls" className="gap-1.5">
            <PackageX className="h-3.5 w-3.5" /> Recalls
          </TabsTrigger>
          <TabsTrigger value="sop" className="gap-1.5">
            <FileText className="h-3.5 w-3.5" /> SOPs
          </TabsTrigger>
          <TabsTrigger value="documents" className="gap-1.5">
            <Database className="h-3.5 w-3.5" /> Documents
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <OverviewTab />
        </TabsContent>
        <TabsContent value="audits">
          <AuditsTab />
        </TabsContent>
        <TabsContent value="deviations">
          <DeviationsTab />
        </TabsContent>
        <TabsContent value="maintenance">
          <MaintenanceTab />
        </TabsContent>
        <TabsContent value="recalls">
          <RecallsTab />
        </TabsContent>
        <TabsContent value="sop">
          <SopTab />
        </TabsContent>
        <TabsContent value="documents">
          <DocumentsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
