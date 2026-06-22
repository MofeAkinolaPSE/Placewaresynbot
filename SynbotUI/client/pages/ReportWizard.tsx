/**
 * ReportWizard — 5-step enterprise report generation wizard.
 *
 * Step 1 — Select report type
 * Step 2 — Fill scope parameters (dynamic per template)
 * Step 3 — Evidence notes + context
 * Step 4 — Review summary before generating
 * Step 5 — View result, download DOCX, approve
 */
import { useState, useCallback } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  FileText,
  ChevronRight,
  ChevronLeft,
  Loader2,
  Download,
  CheckCircle,
  AlertCircle,
  ScrollText,
  BarChart3,
  ClipboardList,
  ShieldCheck,
  DollarSign,
  Package,
  Users,
  TrendingUp,
  Receipt,
  Building2,
  ShoppingBag,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api-client";
import { useToast } from "@/hooks/use-toast";

// ── Type icon map ─────────────────────────────────────────────────────────────
const TYPE_ICONS: Record<string, React.ElementType> = {
  executive:   BarChart3,
  financial:   DollarSign,
  sales:       TrendingUp,
  inventory:   Package,
  payroll:     Users,
  pl:          DollarSign,
  ar_aging:    Receipt,
  compliance:  ShieldCheck,
  audit:       ClipboardList,
  deviation:   AlertCircle,
  maintenance: Building2,
  frontdesk:   ShoppingBag,
  invoice:     ScrollText,
};

// ── Step indicators ───────────────────────────────────────────────────────────
const STEPS = [
  "Report Type",
  "Scope",
  "Notes",
  "Review",
  "Result",
];

// ── Helpers ───────────────────────────────────────────────────────────────────
function StepBar({ current }: { current: number }) {
  return (
    <div className="flex items-center gap-1 mb-8">
      {STEPS.map((label, i) => (
        <div key={label} className="flex items-center gap-1 flex-1">
          <div
            className={`flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold border-2 transition-colors ${
              i < current
                ? "bg-green-600 border-green-600 text-white"
                : i === current
                ? "border-green-600 text-green-700 dark:text-green-400"
                : "border-border text-muted-foreground"
            }`}
          >
            {i < current ? <CheckCircle className="w-4 h-4" /> : i + 1}
          </div>
          <span
            className={`text-xs font-medium hidden sm:block ${
              i === current ? "text-green-700 dark:text-green-400" : "text-muted-foreground"
            }`}
          >
            {label}
          </span>
          {i < STEPS.length - 1 && (
            <div
              className={`flex-1 h-0.5 mx-1 rounded ${
                i < current ? "bg-green-600" : "bg-border"
              }`}
            />
          )}
        </div>
      ))}
    </div>
  );
}

// ── Scope field renderer ──────────────────────────────────────────────────────
function ScopeField({
  field,
  value,
  onChange,
}: {
  field: { key: string; label: string; type: string; required: boolean; options?: string[] };
  value: any;
  onChange: (key: string, val: any) => void;
}) {
  if (field.type === "select" && field.options) {
    return (
      <div className="space-y-1">
        <label className="text-sm font-medium">
          {field.label} {field.required && <span className="text-red-500">*</span>}
        </label>
        <Select value={value ?? ""} onValueChange={(v) => onChange(field.key, v)}>
          <SelectTrigger>
            <SelectValue placeholder={`Select ${field.label.toLowerCase()}`} />
          </SelectTrigger>
          <SelectContent>
            {field.options.map((opt) => (
              <SelectItem key={opt} value={opt}>
                {opt}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
  }
  if (field.type === "date") {
    return (
      <div className="space-y-1">
        <label className="text-sm font-medium">
          {field.label} {field.required && <span className="text-red-500">*</span>}
        </label>
        <Input
          type="date"
          value={value ?? ""}
          onChange={(e) => onChange(field.key, e.target.value)}
        />
      </div>
    );
  }
  if (field.type === "number") {
    return (
      <div className="space-y-1">
        <label className="text-sm font-medium">
          {field.label} {field.required && <span className="text-red-500">*</span>}
        </label>
        <Input
          type="number"
          value={value ?? ""}
          onChange={(e) => onChange(field.key, e.target.value)}
        />
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <label className="text-sm font-medium">
        {field.label} {field.required && <span className="text-red-500">*</span>}
      </label>
      <Input
        type="text"
        value={value ?? ""}
        placeholder={field.label}
        onChange={(e) => onChange(field.key, e.target.value)}
      />
    </div>
  );
}

// ── Score badge ───────────────────────────────────────────────────────────────
function ScoreBadge({ score }: { score: number }) {
  const color =
    score >= 8 ? "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300" :
    score >= 6 ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300" :
                 "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300";
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold ${color}`}>
      Quality: {score.toFixed(1)}/10
    </span>
  );
}

// ── Main wizard component ─────────────────────────────────────────────────────
export default function ReportWizard() {
  const { toast } = useToast();
  const [step, setStep]             = useState(0);
  const [reportType, setReportType] = useState("");
  const [sessionId, setSessionId]   = useState<string | null>(null);
  const [scopeData, setScopeData]   = useState<Record<string, any>>({});
  const [notes, setNotes]           = useState("");
  const [reportResult, setReportResult] = useState<any>(null);
  const [downloading, setDownloading]   = useState(false);
  const [approving, setApproving]       = useState(false);

  // ── Data ────────────────────────────────────────────────────────────────────
  const { data: typesData, isLoading: typesLoading } = useQuery({
    queryKey: ["report-types"],
    queryFn:  () => api.reports.types(),
  });
  const reportTypes = typesData?.report_types ?? [];

  const selectedTypeMeta = reportTypes.find((t) => t.type === reportType);

  // ── Mutations ───────────────────────────────────────────────────────────────
  const createSession = useMutation({
    mutationFn: () => api.reports.createSession(reportType),
    onSuccess: (data) => {
      setSessionId(data.session_id);
      setStep(1);
    },
    onError: (err: any) => toast({ title: "Error", description: err.message, variant: "destructive" }),
  });

  const updateScope = useMutation({
    mutationFn: () =>
      api.reports.updateScope(sessionId!, scopeData, notes || undefined),
    onSuccess: () => setStep(3),
    onError: (err: any) => toast({ title: "Error", description: err.message, variant: "destructive" }),
  });

  const generateReport = useMutation({
    mutationFn: () => api.reports.generateFromSession(sessionId!),
    onSuccess: (data) => {
      setReportResult(data);
      setStep(4);
    },
    onError: (err: any) => toast({ title: "Generation failed", description: err.message, variant: "destructive" }),
  });

  // ── Handlers ────────────────────────────────────────────────────────────────
  const handleScopeChange = useCallback((key: string, val: any) => {
    setScopeData((prev) => ({ ...prev, [key]: val }));
  }, []);

  const handleDownload = async () => {
    if (!reportResult?.report_memory_id) return;
    setDownloading(true);
    try {
      const { url, filename } = await api.reports.downloadDocx(reportResult.report_memory_id);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      toast({ title: "Download failed", description: err.message, variant: "destructive" });
    } finally {
      setDownloading(false);
    }
  };

  const handleApprove = async () => {
    if (!reportResult?.report_memory_id) return;
    setApproving(true);
    try {
      await api.reports.approve(reportResult.report_memory_id);
      toast({ title: "Approved", description: "Report marked as FINAL." });
      setReportResult((prev: any) => ({ ...prev, approved: true }));
    } catch (err: any) {
      toast({ title: "Approval failed", description: err.message, variant: "destructive" });
    } finally {
      setApproving(false);
    }
  };

  // ── Scope field validation ───────────────────────────────────────────────────
  const requiredFields = selectedTypeMeta?.required_scope_fields ?? [];
  const missingRequired = requiredFields.filter(
    (f: any) => f.required && !scopeData[f.key],
  );

  // ── Render steps ─────────────────────────────────────────────────────────────

  // Step 0 — Choose type
  const renderStep0 = () => (
    <div>
      <h2 className="text-xl font-semibold mb-1">Choose Report Type</h2>
      <p className="text-sm text-muted-foreground mb-6">
        Select the kind of report you need. The wizard will collect the right information for each type.
      </p>
      {typesLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading types…
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {reportTypes.map((rt) => {
            const Icon = TYPE_ICONS[rt.type] ?? FileText;
            const active = reportType === rt.type;
            return (
              <button
                key={rt.type}
                onClick={() => setReportType(rt.type)}
                className={`flex items-start gap-3 p-4 rounded-xl border-2 text-left transition-all hover:border-green-500 ${
                  active
                    ? "border-green-600 bg-green-50 dark:bg-green-900/20"
                    : "border-border bg-card"
                }`}
              >
                <div
                  className={`p-2 rounded-lg ${active ? "bg-green-600 text-white" : "bg-muted text-muted-foreground"}`}
                >
                  <Icon className="w-5 h-5" />
                </div>
                <div>
                  <p className="font-medium text-sm">{rt.name}</p>
                  {rt.is_invoice && (
                    <Badge variant="outline" className="text-[10px] mt-0.5">Invoice</Badge>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      )}

      <div className="mt-8 flex justify-end">
        <Button
          disabled={!reportType || createSession.isPending}
          onClick={() => createSession.mutate()}
        >
          {createSession.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
          Next: Configure Scope <ChevronRight className="w-4 h-4 ml-1" />
        </Button>
      </div>
    </div>
  );

  // Step 1 — Scope fields
  const renderStep1 = () => {
    const allFields = selectedTypeMeta?.required_scope_fields ?? [];
    return (
      <div>
        <h2 className="text-xl font-semibold mb-1">Configure Report Scope</h2>
        <p className="text-sm text-muted-foreground mb-6">
          Fill in the parameters that define the scope of this {selectedTypeMeta?.name} report.
          Fields marked <span className="text-red-500">*</span> are required.
        </p>

        {allFields.length === 0 ? (
          <p className="text-sm text-muted-foreground">No scope parameters required for this report type.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {allFields.map((field: any) => (
              <ScopeField
                key={field.key}
                field={field}
                value={scopeData[field.key]}
                onChange={handleScopeChange}
              />
            ))}
          </div>
        )}

        <div className="mt-8 flex justify-between">
          <Button variant="outline" onClick={() => setStep(0)}>
            <ChevronLeft className="w-4 h-4 mr-1" /> Back
          </Button>
          <Button
            onClick={() => setStep(2)}
            disabled={missingRequired.length > 0}
          >
            Next: Context Notes <ChevronRight className="w-4 h-4 ml-1" />
          </Button>
        </div>
        {missingRequired.length > 0 && (
          <p className="text-xs text-red-500 mt-2">
            Please fill: {missingRequired.map((f: any) => f.label).join(", ")}
          </p>
        )}
      </div>
    );
  };

  // Step 2 — Evidence / notes
  const renderStep2 = () => (
    <div>
      <h2 className="text-xl font-semibold mb-1">Evidence & Context Notes</h2>
      <p className="text-sm text-muted-foreground mb-6">
        Optional: add any supporting context, known issues, or evidence the AI should consider.
      </p>
      <Textarea
        rows={8}
        placeholder="e.g. 'Q2 stock discrepancy flagged by warehouse manager. Include deviation DR-2025-041. Focus on cold-chain compliance.'"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        className="resize-none"
      />
      <div className="mt-8 flex justify-between">
        <Button variant="outline" onClick={() => setStep(1)}>
          <ChevronLeft className="w-4 h-4 mr-1" /> Back
        </Button>
        <Button
          onClick={() => updateScope.mutate()}
          disabled={updateScope.isPending}
        >
          {updateScope.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
          Next: Review <ChevronRight className="w-4 h-4 ml-1" />
        </Button>
      </div>
    </div>
  );

  // Step 3 — Review
  const renderStep3 = () => (
    <div>
      <h2 className="text-xl font-semibold mb-1">Review & Generate</h2>
      <p className="text-sm text-muted-foreground mb-6">
        Confirm the details below, then click Generate to start AI report creation.
      </p>

      <div className="space-y-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Report Type</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-medium">{selectedTypeMeta?.name ?? reportType}</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Scope Parameters</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-2 text-sm">
              {Object.entries(scopeData).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <span className="text-muted-foreground capitalize">{k.replace(/_/g, " ")}:</span>
                  <span className="font-medium">{String(v)}</span>
                </div>
              ))}
              {Object.keys(scopeData).length === 0 && (
                <p className="text-muted-foreground col-span-2">No scope constraints — full period.</p>
              )}
            </div>
          </CardContent>
        </Card>

        {notes && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Context Notes</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm whitespace-pre-wrap">{notes}</p>
            </CardContent>
          </Card>
        )}

        {selectedTypeMeta && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Sections to be Generated</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="text-sm list-disc list-inside space-y-1 text-muted-foreground">
                {(selectedTypeMeta as any).sections?.map((s: string, i: number) => (
                  <li key={i}>{s}</li>
                )) ?? <li>Standard report sections</li>}
              </ul>
            </CardContent>
          </Card>
        )}
      </div>

      <div className="mt-8 flex justify-between">
        <Button variant="outline" onClick={() => setStep(2)}>
          <ChevronLeft className="w-4 h-4 mr-1" /> Back
        </Button>
        <Button
          onClick={() => generateReport.mutate()}
          disabled={generateReport.isPending}
          className="bg-green-700 hover:bg-green-800 text-white"
        >
          {generateReport.isPending ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" /> Generating…
            </>
          ) : (
            <>
              Generate Report <ChevronRight className="w-4 h-4 ml-1" />
            </>
          )}
        </Button>
      </div>
    </div>
  );

  // Step 4 — Result
  const renderStep4 = () => {
    if (!reportResult) return null;
    const sections = reportResult.sections ?? [];
    return (
      <div>
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl font-semibold">{reportResult.section_title}</h2>
            <div className="flex items-center gap-2 mt-1">
              <ScoreBadge score={reportResult.quality_score ?? 0} />
              <Badge variant="outline">{reportResult.report_type}</Badge>
              {reportResult.traceability && (
                <span className="text-xs text-muted-foreground">
                  {reportResult.traceability.section_count} sections · {reportResult.traceability.rag_hits} RAG hits
                </span>
              )}
            </div>
          </div>
          <div className="flex gap-2">
            {reportResult.report_memory_id && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleDownload}
                  disabled={downloading}
                >
                  {downloading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4 mr-1" />}
                  Download DOCX
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleApprove}
                  disabled={approving || reportResult.approved}
                  className="text-green-700 border-green-600 hover:bg-green-50"
                >
                  {approving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4 mr-1" />}
                  {reportResult.approved ? "Approved" : "Approve"}
                </Button>
              </>
            )}
          </div>
        </div>

        {sections.length > 0 ? (
          <div className="space-y-4">
            {sections.map((sec: any) => (
              <Card key={sec.id} className={sec.status === "incomplete" ? "opacity-60" : ""}>
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base">{sec.title}</CardTitle>
                    <div className="flex items-center gap-2">
                      {sec.status === "incomplete" && (
                        <Badge variant="destructive" className="text-[10px]">Incomplete</Badge>
                      )}
                      <span className="text-xs text-muted-foreground">
                        {(sec.confidence_score * 100).toFixed(0)}% confidence
                      </span>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <pre className="whitespace-pre-wrap text-sm font-sans leading-relaxed">
                    {sec.content || "[No content generated for this section]"}
                  </pre>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <Card>
            <CardContent className="pt-4">
              <pre className="whitespace-pre-wrap text-sm font-sans leading-relaxed">
                {reportResult.full_report}
              </pre>
            </CardContent>
          </Card>
        )}

        <div className="mt-8 flex gap-3">
          <Button
            variant="outline"
            onClick={() => {
              setStep(0);
              setReportType("");
              setSessionId(null);
              setScopeData({});
              setNotes("");
              setReportResult(null);
            }}
          >
            Generate Another Report
          </Button>
        </div>
      </div>
    );
  };

  const stepRenderers = [renderStep0, renderStep1, renderStep2, renderStep3, renderStep4];

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-2">
      <div className="mb-2">
        <h1 className="text-2xl font-bold">Report Generator</h1>
        <p className="text-sm text-muted-foreground">
          Enterprise AI-powered, section-by-section intelligent reports
        </p>
      </div>

      <Card>
        <CardContent className="pt-6">
          <StepBar current={step} />
          {stepRenderers[step]?.()}
        </CardContent>
      </Card>
    </div>
  );
}
