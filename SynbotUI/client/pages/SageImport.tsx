import { useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import {
  Upload,
  File,
  CheckCircle,
  AlertCircle,
  Clock,
  Package,
  ShoppingCart,
  BarChart3,
  FileText,
  Warehouse,
  Users,
  UserCheck,
  BookOpen,
  Truck,
  RefreshCw,
} from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { authClient } from "@/lib/auth-client";
import { format } from "date-fns";
import { motion } from "framer-motion";
import { motionTransitions } from "@/lib/motion";

// ---------------------------------------------------------------------------
// Types — slugs must match backend _REGISTRY exactly
// ---------------------------------------------------------------------------

type SageFileType =
  | "chart_of_accounts"
  | "vendors"
  | "customers"
  | "items"
  | "stock_on_hand"
  | "purchase_orders"
  | "sales_invoices"
  | "sales_invoice_lines"
  | "inventory_transactions"
  | "gl_journal_entries"
  | "staff";

type CardStatus = "idle" | "uploading" | "success" | "error";

interface CardResult {
  rows_inserted: number;
  batch_id: string;
  validation_error_count: number;
  validation_errors: string[];
  status: string;
}

// ---------------------------------------------------------------------------
// Dataset registry — 10 supported document types
// ---------------------------------------------------------------------------

const DATASETS: {
  id: SageFileType;
  label: string;
  description: string;
  icon: React.ElementType;
}[] = [
  {
    id: "chart_of_accounts",
    label: "Chart of Accounts",
    description: "Account code hierarchy (COA)",
    icon: BookOpen,
  },
  {
    id: "vendors",
    label: "Vendors",
    description: "Supplier master list",
    icon: Truck,
  },
  {
    id: "customers",
    label: "Customers",
    description: "Customer master list",
    icon: Users,
  },
  {
    id: "items",
    label: "Product Items",
    description: "SKU / product catalogue",
    icon: Package,
  },
  {
    id: "stock_on_hand",
    label: "Stock on Hand",
    description: "Warehouse inventory balances",
    icon: Warehouse,
  },
  {
    id: "purchase_orders",
    label: "Purchase Orders",
    description: "Supplier PO history",
    icon: ShoppingCart,
  },
  // sales_invoices / sales_invoice_lines moved to the dedicated "Daily
  // Invoice Refresh" panel above this grid — still valid SageFileType/
  // _REGISTRY entries, just no longer duplicated as generic cards here.
  {
    id: "inventory_transactions",
    label: "Inventory Transactions",
    description: "Stock movement ledger",
    icon: Warehouse,
  },
  {
    id: "gl_journal_entries",
    label: "GL Journal Entries",
    description: "General Ledger double-entry journal",
    icon: BookOpen,
  },
  {
    id: "staff",
    label: "Staff Registry",
    description: "Employee / staff master list",
    icon: Users,
  },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const SageImport = () => {
  const [fileMap, setFileMap] = useState<Partial<Record<SageFileType, File>>>({});
  const [cardStatus, setCardStatus] = useState<Partial<Record<SageFileType, CardStatus>>>({});
  const [cardResult, setCardResult] = useState<Partial<Record<SageFileType, CardResult>>>({});
  const [uploadingAll, setUploadingAll] = useState(false);

  // ── HR import state ──────────────────────────────────────────────────────
  const [hrFiles, setHrFiles] = useState<{ payroll: File | null; absences: File | null }>({
    payroll: null,
    absences: null,
  });
  const [hrStatus, setHrStatus] = useState<CardStatus>("idle");
  const [hrResult, setHrResult] = useState<{ counts?: { payroll?: number; absences?: number }; batch_id?: string } | null>(null);

  const {
    data: historyData,
    refetch: refetchHistory,
    isFetching: historyFetching,
  } = useQuery({
    queryKey: ["sage-import-jobs"],
    queryFn: () => api.sage.importJobs(30),
    refetchInterval: 30_000,
  });

  const jobs = historyData?.data ?? [];

  const { data: freshnessData, refetch: refetchFreshness } = useQuery({
    queryKey: ["sage-import-freshness"],
    queryFn: () => api.sage.freshness(),
    refetchInterval: 60_000,
  });

  const arLastImported = freshnessData?.last_imported?.sales_invoices ?? null;
  const arDaysAgo = arLastImported
    ? Math.floor((Date.now() - new Date(arLastImported).getTime()) / 86_400_000)
    : null;
  // Daily-refresh cadence with one day of slack before flagging as stale.
  const arIsStale = arDaysAgo !== null && arDaysAgo > 2;

  // ── File selection ────────────────────────────────────────────────────────

  const handleFileChange = useCallback(
    (fileType: SageFileType, e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0];
      if (!f) return;
      const name = f.name.toLowerCase();
      if (!name.endsWith(".csv") && !name.endsWith(".xlsx")) {
        toast.error("Only .csv or .xlsx files are accepted");
        return;
      }
      setFileMap((prev) => ({ ...prev, [fileType]: f }));
      // Reset card state when a new file is chosen
      setCardStatus((prev) => ({ ...prev, [fileType]: "idle" }));
      setCardResult((prev) => {
        const next = { ...prev };
        delete next[fileType];
        return next;
      });
      toast.success(`${f.name} ready for ${fileType}`);
    },
    [],
  );

  // ── Individual card upload ────────────────────────────────────────────────

  const uploadCard = useCallback(
    async (fileType: SageFileType): Promise<boolean> => {
      const file = fileMap[fileType];
      if (!file) {
        toast.error(`No file selected for ${fileType}`);
        return false;
      }

      setCardStatus((prev) => ({ ...prev, [fileType]: "uploading" }));

      try {
        const refreshed = await authClient.refresh();
        if (!refreshed && !authClient.getAccessToken()) {
          throw new Error("Session expired. Please sign in again.");
        }

        const result = await api.imports.importCsv(fileType, file);

        setCardStatus((prev) => ({ ...prev, [fileType]: "success" }));
        setCardResult((prev) => ({ ...prev, [fileType]: result }));

        const note =
          result.validation_error_count > 0
            ? ` (${result.validation_error_count} validation warning${result.validation_error_count > 1 ? "s" : ""})`
            : "";
        toast.success(`${result.rows_inserted} rows imported — ${fileType}${note}`);
        if (fileType === "sales_invoices" || fileType === "sales_invoice_lines") {
          refetchFreshness();
        }
        return true;
      } catch (e: any) {
        const message =
          typeof e?.message === "string" && e.message.trim()
            ? e.message
            : "Unknown import error";
        setCardStatus((prev) => ({ ...prev, [fileType]: "error" }));
        console.error("Sage CSV import failed", { fileType, message, error: e });
        toast.error(`${fileType}: ${message}`);
        return false;
      }
    },
    [fileMap, refetchFreshness],
  );

  // ── HR file selection ──────────────────────────────────────────────────────

  const handleHrFileChange = useCallback(
    (field: "payroll" | "absences", e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0];
      if (!f) return;
      if (!f.name.toLowerCase().endsWith(".csv")) {
        toast.error("Only .csv files are accepted");
        return;
      }
      setHrFiles((prev) => ({ ...prev, [field]: f }));
      if (hrStatus === "success" || hrStatus === "error") {
        setHrStatus("idle");
        setHrResult(null);
      }
      toast.success(`${f.name} ready for HR ${field}`);
    },
    [hrStatus],
  );

  // ── HR upload ─────────────────────────────────────────────────────────────

  const uploadHr = useCallback(async () => {
    if (!hrFiles.payroll && !hrFiles.absences) {
      toast.error("Select at least one HR CSV file");
      return;
    }
    setHrStatus("uploading");
    try {
      const refreshed = await authClient.refresh();
      if (!refreshed && !authClient.getAccessToken()) {
        throw new Error("Session expired. Please sign in again.");
      }
      const fd = new FormData();
      if (hrFiles.payroll) fd.append("payroll", hrFiles.payroll);
      if (hrFiles.absences) fd.append("absences", hrFiles.absences);
      const result = await api.imports.hr(fd);
      setHrStatus("success");
      setHrResult(result);
      const parts: string[] = [];
      if (result?.counts?.payroll != null) parts.push(`${result.counts.payroll} payroll rows`);
      if (result?.counts?.absences != null) parts.push(`${result.counts.absences} absence rows`);
      toast.success(`HR import complete — ${parts.join(", ") || "data uploaded"}`);
      refetchHistory();
    } catch (e: any) {
      setHrStatus("error");
      const message =
        typeof e?.message === "string" && e.message.trim() ? e.message : "Unknown HR import error";
      toast.error(`HR import: ${message}`);
    }
  }, [hrFiles, hrStatus, refetchHistory]);

  // ── Batch upload all ready cards ─────────────────────────────────────────

  const handleUploadAll = async () => {
    const pending = DATASETS.map((d) => d.id).filter(
      (id) => fileMap[id] && cardStatus[id] !== "success",
    );
    if (pending.length === 0) {
      toast.error("No files selected (or all already uploaded)");
      return;
    }
    setUploadingAll(true);
    for (const fileType of pending) {
      await uploadCard(fileType);
    }
    setUploadingAll(false);
    refetchHistory();
  };

  // ── Helpers ───────────────────────────────────────────────────────────────

  const getCardStatusIcon = (status: CardStatus) => {
    switch (status) {
      case "success":
        return <CheckCircle className="w-4 h-4 text-success" />;
      case "error":
        return <AlertCircle className="w-4 h-4 text-destructive" />;
      case "uploading":
        return (
          <div className="animate-spin h-4 w-4 border-2 border-current border-t-transparent rounded-full" />
        );
      default:
        return null;
    }
  };

  const getJobStatusIcon = (status: string) => {
    if (status === "succeeded" || status === "success")
      return <CheckCircle className="w-4 h-4 text-success" />;
    if (status === "failed" || status === "error")
      return <AlertCircle className="w-4 h-4 text-destructive" />;
    return <Clock className="w-4 h-4 text-muted-foreground" />;
  };

  const readyCount = DATASETS.filter(
    (d) => fileMap[d.id] && cardStatus[d.id] !== "success",
  ).length;

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={motionTransitions.standard}
      className="pw-page-surface space-y-8 p-8"
    >
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-foreground">Sage CSV Import</h1>
        <p className="text-muted-foreground mt-2">
          Import ERP data from Sage 50 into ACE — all 10 document types supported.
        </p>
      </div>

      {/* Daily Invoice Refresh — the primary recurring workflow */}
      <div
        className={`pw-surface-interactive rounded-xl p-6 space-y-4 border ${
          arIsStale ? "border-warning/50" : "border-info/30"
        }`}
      >
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-foreground">Daily Invoice Refresh</h2>
            <p className="text-sm text-muted-foreground">
              Export these from Sage 50 and upload here to keep AR aging, credit risk, and
              customer profitability current. Recommended cadence: daily.
            </p>
          </div>
          <div
            className={`text-xs font-medium rounded-lg px-3 py-1.5 whitespace-nowrap ${
              arLastImported === null
                ? "bg-muted text-muted-foreground"
                : arIsStale
                ? "bg-warning/15 text-warning"
                : "bg-success/15 text-success"
            }`}
          >
            {arLastImported === null
              ? "No invoice data uploaded yet"
              : arDaysAgo === 0
              ? "AR data updated today"
              : `AR data last updated ${arDaysAgo} day${arDaysAgo === 1 ? "" : "s"} ago`}
            {arIsStale && " — overdue for refresh"}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {(
            [
              {
                id: "sales_invoices" as SageFileType,
                label: "Customer Management Details",
                description: "Required — invoice #, due date, outstanding balance per customer",
                icon: FileText,
                required: true,
              },
              {
                id: "sales_invoice_lines" as SageFileType,
                label: "Items Sold to Customers",
                description: "Optional — keeps product-level sales & margin data fresh (CRM 360)",
                icon: BarChart3,
                required: false,
              },
            ] as const
          ).map((slot) => {
            const file = fileMap[slot.id];
            const status = cardStatus[slot.id] ?? "idle";
            const result = cardResult[slot.id];
            const Icon = slot.icon;
            return (
              <div key={slot.id} className="rounded-lg border border-border/60 p-4 flex flex-col gap-2">
                <input
                  type="file"
                  id={`file-daily-${slot.id}`}
                  className="hidden"
                  accept=".csv,.xlsx"
                  onChange={(e) => handleFileChange(slot.id, e)}
                />
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <Icon className="w-4 h-4 text-muted-foreground" />
                    <span className="text-sm font-medium text-foreground">{slot.label}</span>
                    {!slot.required && (
                      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">optional</span>
                    )}
                  </div>
                  {getCardStatusIcon(status)}
                </div>
                <p className="text-xs text-muted-foreground">{slot.description}</p>
                {file && (
                  <p className="text-xs text-muted-foreground truncate" title={file.name}>
                    📎 {file.name}
                  </p>
                )}
                {result && (
                  <p className="text-xs text-success font-medium">
                    {result.rows_inserted.toLocaleString()} rows inserted
                  </p>
                )}
                <div className="flex gap-2 mt-1">
                  <Button
                    size="sm"
                    variant="outline"
                    className="flex-1 text-xs"
                    onClick={() => document.getElementById(`file-daily-${slot.id}`)?.click()}
                    disabled={status === "uploading"}
                  >
                    <File className="w-3 h-3 mr-1" />
                    {file ? "Change" : "Choose File"}
                  </Button>
                  <Button
                    size="sm"
                    variant={status === "success" ? "secondary" : "default"}
                    className="flex-1 text-xs"
                    onClick={() => uploadCard(slot.id)}
                    disabled={!file || status === "uploading"}
                  >
                    {status === "uploading" ? (
                      <div className="animate-spin h-3 w-3 border-2 border-current border-t-transparent rounded-full" />
                    ) : (
                      "Upload"
                    )}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Batch upload bar */}
      {readyCount > 0 && (
        <div className="flex items-center justify-between rounded-xl border border-info/30 bg-info/15 p-4">
          <p className="text-sm font-medium text-info">
            {readyCount} file{readyCount > 1 ? "s" : ""} ready to import
          </p>
          <Button
            onClick={handleUploadAll}
            disabled={uploadingAll}
            size="sm"
          >
            {uploadingAll ? (
              <>
                <div className="animate-spin mr-2 h-3 w-3 border-2 border-current border-t-transparent rounded-full" />
                Uploading all…
              </>
            ) : (
              <>
                <Upload className="w-3 h-3 mr-2" />
                Upload All Ready
              </>
            )}
          </Button>
        </div>
      )}

      {/* Upload Cards — all 10 document types */}
      <div className="space-y-4">
        <h2 className="text-lg font-semibold text-foreground">Document Types</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {DATASETS.map((dataset) => {
            const file = fileMap[dataset.id];
            const status = cardStatus[dataset.id] ?? "idle";
            const result = cardResult[dataset.id];
            const Icon = dataset.icon;

            return (
              <div
                key={dataset.id}
                className={`pw-surface-interactive rounded-xl p-5 flex flex-col gap-3 transition-colors ${
                  status === "success"
                    ? "border border-success/30"
                    : status === "error"
                    ? "border border-destructive/30"
                    : ""
                }`}
              >
                <input
                  type="file"
                  id={`file-${dataset.id}`}
                  className="hidden"
                  accept=".csv,.xlsx"
                  onChange={(e) => handleFileChange(dataset.id, e)}
                />

                {/* Card header */}
                <div className="flex items-start justify-between">
                  <Icon className="w-6 h-6 text-muted-foreground" />
                  {getCardStatusIcon(status)}
                </div>

                {/* Title + description */}
                <div>
                  <h3 className="font-semibold text-foreground text-sm">
                    {dataset.label}
                  </h3>
                  <p className="text-xs text-muted-foreground">{dataset.description}</p>
                </div>

                {/* Selected filename */}
                {file && (
                  <p
                    className="text-xs text-muted-foreground truncate"
                    title={file.name}
                  >
                    📎 {file.name}
                  </p>
                )}

                {/* Per-card import result */}
                {result && (
                  <div className="text-xs space-y-0.5">
                    <p className="text-success font-medium">
                      {result.rows_inserted.toLocaleString()} rows inserted
                    </p>
                    {result.validation_error_count > 0 && (
                      <p className="text-yellow-500">
                        ⚠ {result.validation_error_count} validation warning
                        {result.validation_error_count > 1 ? "s" : ""}
                      </p>
                    )}
                    <p className="font-mono text-muted-foreground truncate">
                      {result.batch_id.slice(0, 8)}…
                    </p>
                  </div>
                )}

                {/* Actions */}
                <div className="flex gap-2 mt-auto">
                  <Button
                    size="sm"
                    variant="outline"
                    className="flex-1 text-xs"
                    onClick={() =>
                      document.getElementById(`file-${dataset.id}`)?.click()
                    }
                    disabled={status === "uploading"}
                  >
                    <File className="w-3 h-3 mr-1" />
                    {file ? "Change" : "Choose File"}
                  </Button>
                  <Button
                    size="sm"
                    variant={status === "success" ? "secondary" : "default"}
                    className="flex-1 text-xs"
                    onClick={() => uploadCard(dataset.id)}
                    disabled={!file || status === "uploading" || status === "success"}
                  >
                    {status === "uploading" ? (
                      <div className="animate-spin h-3 w-3 border-2 border-current border-t-transparent rounded-full" />
                    ) : status === "success" ? (
                      <>
                        <CheckCircle className="w-3 h-3 mr-1" />
                        Done
                      </>
                    ) : (
                      <>
                        <Upload className="w-3 h-3 mr-1" />
                        Upload
                      </>
                    )}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* HR Data Import */}
      <div className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-foreground">HR Data Import</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Upload payroll and absence records to power HR analytics, absenteeism trends, and overtime KPIs.
          </p>
        </div>
        <div
          className={`pw-surface-interactive rounded-xl p-6 transition-colors ${
            hrStatus === "success"
              ? "border border-success/30"
              : hrStatus === "error"
              ? "border border-destructive/30"
              : ""
          }`}
        >
          {/* Card header */}
          <div className="flex items-center gap-3 mb-6">
            <UserCheck className="w-6 h-6 text-muted-foreground" />
            <div>
              <h3 className="font-semibold text-foreground">Payroll &amp; Absences</h3>
              <p className="text-xs text-muted-foreground">
                Two separate CSV files — submit together or individually
              </p>
            </div>
            {hrStatus !== "idle" && (
              <div className="ml-auto">{getCardStatusIcon(hrStatus)}</div>
            )}
          </div>

          {/* File pickers */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            {/* Payroll */}
            <div
              className={`rounded-lg border p-4 ${
                hrFiles.payroll ? "border-info/40 bg-info/5" : "border-border"
              }`}
            >
              <p className="text-sm font-medium text-foreground mb-1">Payroll CSV</p>
              <p className="text-xs text-muted-foreground mb-3">
                Columns: <span className="font-mono">employee_id, salary, overtime_hours, overtime_rate</span>
              </p>
              {hrFiles.payroll && (
                <p
                  className="text-xs text-muted-foreground truncate mb-3"
                  title={hrFiles.payroll.name}
                >
                  📎 {hrFiles.payroll.name}
                </p>
              )}
              <input
                type="file"
                id="hr-payroll-file"
                className="hidden"
                accept=".csv"
                onChange={(e) => handleHrFileChange("payroll", e)}
              />
              <Button
                size="sm"
                variant="outline"
                className="w-full text-xs"
                onClick={() => document.getElementById("hr-payroll-file")?.click()}
                disabled={hrStatus === "uploading"}
              >
                <File className="w-3 h-3 mr-1" />
                {hrFiles.payroll ? "Change Payroll CSV" : "Choose Payroll CSV"}
              </Button>
            </div>

            {/* Absences */}
            <div
              className={`rounded-lg border p-4 ${
                hrFiles.absences ? "border-info/40 bg-info/5" : "border-border"
              }`}
            >
              <p className="text-sm font-medium text-foreground mb-1">Absences CSV</p>
              <p className="text-xs text-muted-foreground mb-3">
                Columns: <span className="font-mono">employee_id, date, hours, reason</span>
              </p>
              {hrFiles.absences && (
                <p
                  className="text-xs text-muted-foreground truncate mb-3"
                  title={hrFiles.absences.name}
                >
                  📎 {hrFiles.absences.name}
                </p>
              )}
              <input
                type="file"
                id="hr-absences-file"
                className="hidden"
                accept=".csv"
                onChange={(e) => handleHrFileChange("absences", e)}
              />
              <Button
                size="sm"
                variant="outline"
                className="w-full text-xs"
                onClick={() => document.getElementById("hr-absences-file")?.click()}
                disabled={hrStatus === "uploading"}
              >
                <File className="w-3 h-3 mr-1" />
                {hrFiles.absences ? "Change Absences CSV" : "Choose Absences CSV"}
              </Button>
            </div>
          </div>

          {/* Import result */}
          {hrResult && hrStatus === "success" && (
            <div className="text-sm space-y-1 mb-4 p-3 rounded-lg bg-success/10 border border-success/30">
              {hrResult.counts?.payroll != null && (
                <p className="text-success font-medium">
                  ✓ {hrResult.counts.payroll.toLocaleString()} payroll records imported
                </p>
              )}
              {hrResult.counts?.absences != null && (
                <p className="text-success font-medium">
                  ✓ {hrResult.counts.absences.toLocaleString()} absence records imported
                </p>
              )}
              {hrResult.batch_id && (
                <p className="text-xs font-mono text-muted-foreground">
                  batch: {hrResult.batch_id.slice(0, 8)}…
                </p>
              )}
            </div>
          )}

          {/* Submit */}
          <Button
            onClick={uploadHr}
            disabled={
              (!hrFiles.payroll && !hrFiles.absences) ||
              hrStatus === "uploading" ||
              hrStatus === "success"
            }
            className="w-full"
            variant={hrStatus === "success" ? "secondary" : "default"}
          >
            {hrStatus === "uploading" ? (
              <>
                <div className="animate-spin mr-2 h-4 w-4 border-2 border-current border-t-transparent rounded-full" />
                Uploading HR data…
              </>
            ) : hrStatus === "success" ? (
              <>
                <CheckCircle className="w-4 h-4 mr-2" />
                HR Data Imported
              </>
            ) : (
              <>
                <Upload className="w-4 h-4 mr-2" />
                Upload HR Data
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Import Jobs History */}
      <div className="pw-surface-interactive rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-foreground">Import History</h2>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => refetchHistory()}
            disabled={historyFetching}
            aria-label="Refresh import history"
          >
            <RefreshCw className={`w-4 h-4 ${historyFetching ? "animate-spin" : ""}`} />
          </Button>
        </div>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Imported At</TableHead>
                <TableHead>Document Type</TableHead>
                <TableHead>Rows</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Batch ID</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="text-center text-muted-foreground h-24"
                  >
                    No import history found.
                  </TableCell>
                </TableRow>
              )}
              {jobs.map((job: any) => (
                <TableRow key={job.id ?? job.batch_id}>
                  <TableCell className="font-mono text-sm">
                    {job.imported_at
                      ? format(new Date(job.imported_at), "yyyy-MM-dd HH:mm")
                      : "-"}
                  </TableCell>
                  <TableCell className="text-sm font-medium">
                    {job.metadata?.file_type ?? job.domain ?? "-"}
                  </TableCell>
                  <TableCell className="text-sm">
                    {job.row_count != null ? job.row_count.toLocaleString() : "-"}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      {getJobStatusIcon(job.status)}
                      <span
                        className={`text-xs font-medium capitalize ${
                          job.status === "succeeded" || job.status === "success"
                            ? "text-success"
                            : job.status === "failed" || job.status === "error"
                            ? "text-destructive"
                            : "text-muted-foreground"
                        }`}
                      >
                        {job.status}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {job.batch_id ? `${job.batch_id.slice(0, 8)}…` : "-"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </motion.div>
  );
};

export default SageImport;
