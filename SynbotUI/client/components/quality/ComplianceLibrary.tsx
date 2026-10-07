// Compliance library: SOP index and generated documents (unchanged from the Compliance page).
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

export function DocumentsTab() {
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

export function SopTab() {
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

