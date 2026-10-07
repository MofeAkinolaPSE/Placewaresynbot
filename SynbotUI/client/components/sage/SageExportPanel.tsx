import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  endOfWeek,
  format,
  startOfMonth,
  startOfWeek,
  subWeeks,
} from "date-fns";
import { toast } from "sonner";
import {
  AlertTriangle,
  Banknote,
  CalendarDays,
  CheckCircle2,
  Columns3,
  Download,
  Eye,
  FileText,
  FolderDown,
  Info,
  Lock,
  PackageMinus,
  Receipt,
  RefreshCw,
  Settings2,
  ShoppingCart,
  Trash2,
  Users,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import {
  api,
  type SageExportDoc,
  type SageExportDocInfo,
  type SageExportSettings,
} from "@/lib/api-client";

/**
 * Export to Sage — one card per Sage Import/Export template, mirroring
 * Sage's own File > Select Import/Export screen. Each document is previewed,
 * its columns chosen (Sage's "Fields" tab), and exported on its own, saved
 * under Sage's default file name (SALES.CSV …) into the folder the user
 * picks — Documents by default.
 *
 * Sage 50 2013 has no write API; once these files are imported Sage posts
 * the GL, P&L, balance sheet and stock itself.
 */

type CardDef = {
  doc: SageExportDoc | "purchases" | "payments";
  step?: number;
  title: string;
  sagePath: string;
  icon: LucideIcon;
  unit: string;
  what: string;
};

const CARDS: CardDef[] = [
  {
    doc: "customer",
    step: 1,
    title: "Customer List",
    sagePath: "Accounts Receivable › Customer List",
    icon: Users,
    unit: "new customers",
    what: "Customers on ACE invoices that Sage doesn't have yet.",
  },
  {
    doc: "sales",
    step: 2,
    title: "Sales Journal",
    sagePath: "Accounts Receivable › Sales Journal",
    icon: FileText,
    unit: "invoices",
    what: "Approved ACE invoices. Updates receivables, revenue, cost of sales and stock.",
  },
  {
    doc: "receipts",
    step: 3,
    title: "Cash Receipts Journal",
    sagePath: "Accounts Receivable › Cash Receipts Journal",
    icon: Receipt,
    unit: "receipts",
    what: "Customer payments recorded in ACE. Updates bank/cash and clears invoices.",
  },
  {
    doc: "adjust",
    step: 4,
    title: "Inventory Adjustments",
    sagePath: "Inventory › Adjustments Journal",
    icon: PackageMinus,
    unit: "adjustments",
    what: "Damaged, expired and counted-stock corrections recorded in ACE.",
  },
  {
    doc: "purchases",
    title: "Purchases Journal",
    sagePath: "Accounts Payable › Purchases Journal",
    icon: ShoppingCart,
    unit: "",
    what: "Supplier bills are still entered in Sage — ACE doesn't record goods received yet.",
  },
  {
    doc: "payments",
    title: "Payments Journal",
    sagePath: "Accounts Payable › Payments Journal",
    icon: Banknote,
    unit: "",
    what: "Supplier payments are still entered in Sage.",
  },
];

const FILE_DOC: Record<string, SageExportDoc> = {
  "CUSTOMER.CSV": "customer",
  "SALES.CSV": "sales",
  "RECEIPTS.CSV": "receipts",
  "ADJUST.CSV": "adjust",
};

const isExportable = (d: CardDef["doc"]): d is SageExportDoc =>
  d === "customer" || d === "sales" || d === "receipts" || d === "adjust";

const naira = (n?: number) =>
  `₦${(n ?? 0).toLocaleString("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const iso = (d: Date) => format(d, "yyyy-MM-dd");

type Preset = "pending" | "this_week" | "last_week" | "this_month" | "custom";

function presetRange(p: Preset, cutover: string | null): { from: string; to: string } {
  const now = new Date();
  switch (p) {
    case "this_week":
      return { from: iso(startOfWeek(now, { weekStartsOn: 1 })), to: iso(now) };
    case "last_week": {
      const lw = subWeeks(now, 1);
      return {
        from: iso(startOfWeek(lw, { weekStartsOn: 1 })),
        to: iso(endOfWeek(lw, { weekStartsOn: 1 })),
      };
    }
    case "this_month":
      return { from: iso(startOfMonth(now)), to: iso(now) };
    default:
      // Everything not yet exported: nothing is ever exported twice, so
      // "since the cut-over date" is the natural default.
      return { from: cutover ?? iso(startOfMonth(now)), to: iso(now) };
  }
}

// ---------------------------------------------------------------------------
// Saving: Chrome/Edge's save dialog opens in Documents with Sage's file name
// pre-filled, and remembers the folder chosen for next time. Browsers can't
// write to a folder silently, so other browsers fall back to a download.
// ---------------------------------------------------------------------------

type SaveHandle = { name: string; createWritable: () => Promise<any> };

async function pickSaveLocation(fileName: string): Promise<SaveHandle | null | "cancelled"> {
  const w = window as any;
  if (typeof w.showSaveFilePicker !== "function") return null;
  try {
    return await w.showSaveFilePicker({
      id: "ace-sage-export",
      startIn: "documents",
      suggestedName: fileName,
      types: [{ description: "Sage import file (CSV)", accept: { "text/csv": [".csv", ".CSV"] } }],
    });
  } catch (e: any) {
    if (e?.name === "AbortError") return "cancelled";
    return null; // blocked (e.g. iframe/permissions) -> plain download
  }
}

async function saveBlob(blob: Blob, fileName: string, handle: SaveHandle | null) {
  if (handle) {
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
    return `Saved ${handle.name} to the folder you chose`;
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.click();
  URL.revokeObjectURL(url);
  return `${fileName} downloaded — move it to Documents if Sage looks there`;
}

// ---------------------------------------------------------------------------

export function SageExportPanel() {
  const qc = useQueryClient();
  const [preset, setPreset] = useState<Preset>("pending");
  const [custom, setCustom] = useState(() => presetRange("this_month", null));
  const [selected, setSelected] = useState<SageExportDoc>("sales");
  const [exporting, setExporting] = useState<SageExportDoc | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const settings = useQuery({
    queryKey: ["sage-export-settings"],
    queryFn: () => api.sageExport.settings(),
    staleTime: 0,
  });
  const cutover = settings.data?.cutover_date ?? null;
  const range = preset === "custom" ? custom : presetRange(preset, cutover);

  const preview = useQuery({
    queryKey: ["sage-export-preview", range.from, range.to],
    queryFn: () => api.sageExport.preview(range.from, range.to),
    enabled: settings.isSuccess,
    staleTime: 0,
  });
  const batches = useQuery({
    queryKey: ["sage-export-batches"],
    queryFn: () => api.sageExport.batches(),
    staleTime: 0,
  });

  const plan = preview.data;
  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ["sage-export-preview"] });
    qc.invalidateQueries({ queryKey: ["sage-export-batches"] });
    qc.invalidateQueries({ queryKey: ["sage-export-settings"] });
  };

  /** Why a document can't be exported right now (null = it can). */
  const blockedReason = (doc: SageExportDoc, info?: SageExportDocInfo): string | null => {
    if (!cutover) return "Set the cut-over date first (Export settings)";
    if (!info) return "Loading…";
    if (info.depends_on) return info.depends_on;
    if (info.records === 0)
      return info.blocked > 0
        ? `Nothing ready — ${info.blocked} held back (see Held back)`
        : "Nothing new in this period";
    return null;
  };

  const exportDoc = async (doc: SageExportDoc) => {
    const info = plan?.docs[doc];
    if (!info) return;
    // Ask where to save BEFORE generating: the browser only allows the save
    // dialog straight from the click, and a cancelled dialog must not mark
    // anything as exported.
    const handle = await pickSaveLocation(info.file_name);
    if (handle === "cancelled") return;
    setExporting(doc);
    try {
      const batch = await api.sageExport.generate(range.from, range.to, [doc]);
      const blob = await api.sageExport.fileBlob(batch.id, info.file_name);
      toast.success(await saveBlob(blob, info.file_name, handle), {
        description: `In Sage's Import window, Options tab: tick "First Row Contains Headings" before OK.`,
        duration: 12000,
      });
      refreshAll();
    } catch (e: any) {
      toast.error(e?.message ?? "Export failed");
    } finally {
      setExporting(null);
    }
  };

  const redownload = async (batchId: string, fileName: string) => {
    const handle = await pickSaveLocation(fileName);
    if (handle === "cancelled") return;
    try {
      const blob = await api.sageExport.fileBlob(batchId, fileName);
      toast.success(await saveBlob(blob, fileName, handle));
    } catch (e: any) {
      toast.error(e?.message ?? "Download failed");
    }
  };

  const removeBatch = async (id: string) => {
    if (
      !window.confirm(
        "Undo this export?\n\nOnly do this if the file was NOT imported into Sage " +
          "(e.g. the import failed). Its records become exportable again — importing " +
          "them twice would post them twice in Sage.",
      )
    )
      return;
    try {
      await api.sageExport.deleteBatch(id);
      toast.success("Export undone — its records can be exported again");
      refreshAll();
    } catch (e: any) {
      toast.error(e?.message ?? "Undo failed");
    }
  };

  const selectedInfo = plan?.docs[selected];
  const selectedCard = CARDS.find((c) => c.doc === selected)!;

  return (
    <div className="space-y-6">
      {/* ── Period + status bar ─────────────────────────────────────────── */}
      <div className="pw-surface-interactive rounded-xl border p-5 space-y-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-foreground">Send ACE activity to Sage</h2>
            <p className="text-sm text-muted-foreground">
              Pick a document, check what's in it, export it, then import it in Sage via{" "}
              <strong>File → Select Import/Export</strong>.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {cutover ? (
              <Badge variant="outline" className="gap-1">
                <CheckCircle2 className="w-3.5 h-3.5 text-success" />
                ACE owns invoices &amp; receipts from {format(new Date(cutover), "d MMM yyyy")}
              </Badge>
            ) : (
              <Badge variant="outline" className="gap-1 border-warning/50 text-warning">
                <AlertTriangle className="w-3.5 h-3.5" /> Cut-over date not set
              </Badge>
            )}
            <Button variant="outline" size="sm" onClick={() => setSettingsOpen(true)}>
              <Settings2 className="w-4 h-4 mr-1.5" /> Settings
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <CalendarDays className="w-4 h-4 text-muted-foreground mb-2.5" />
          {(
            [
              ["pending", "Not yet exported"],
              ["this_week", "This week"],
              ["last_week", "Last week"],
              ["this_month", "This month"],
              ["custom", "Custom"],
            ] as [Preset, string][]
          ).map(([p, label]) => (
            <Button
              key={p}
              size="sm"
              variant={preset === p ? "default" : "outline"}
              onClick={() => setPreset(p)}
            >
              {label}
            </Button>
          ))}
          {preset === "custom" && (
            <div className="flex items-end gap-2">
              <Input
                type="date"
                className="h-9 w-40"
                value={custom.from}
                max={custom.to}
                onChange={(e) => setCustom((c) => ({ ...c, from: e.target.value }))}
              />
              <span className="text-muted-foreground mb-2">→</span>
              <Input
                type="date"
                className="h-9 w-40"
                value={custom.to}
                min={custom.from}
                onChange={(e) => setCustom((c) => ({ ...c, to: e.target.value }))}
              />
            </div>
          )}
          <span className="text-sm text-muted-foreground mb-2 ml-1">
            {format(new Date(range.from), "d MMM")} – {format(new Date(range.to), "d MMM yyyy")}
          </span>
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            onClick={refreshAll}
            disabled={preview.isFetching}
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${preview.isFetching ? "animate-spin" : ""}`} />
          </Button>
        </div>

        {plan?.warnings
          .filter((w) => !w.toLowerCase().includes("cut-over"))
          .map((w) => (
            <div key={w} className="flex items-start gap-2 rounded-lg bg-warning/15 text-warning px-3 py-2 text-sm">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /> {w}
            </div>
          ))}
        {preview.isError && (
          <p className="text-sm text-destructive">{(preview.error as Error)?.message}</p>
        )}
      </div>

      {/* ── Needs manual reversal ───────────────────────────────────────── */}
      {!!plan?.needs_reversal.length && (
        <div className="rounded-xl border border-destructive/40 p-4 space-y-1">
          <h3 className="font-semibold text-destructive flex items-center gap-2">
            <AlertTriangle className="w-4 h-4" /> Void these in Sage by hand
          </h3>
          <p className="text-sm text-muted-foreground">
            Already sent to Sage, then cancelled or voided in ACE. An import can't undo them.
          </p>
          <p className="text-sm">
            {plan.needs_reversal.map((r) => `${r.ref} (${r.status})`).join(" · ")}
          </p>
        </div>
      )}

      {/* ── Document cards ──────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {CARDS.map((card) => {
          const Icon = card.icon;
          if (!isExportable(card.doc)) {
            return (
              <div key={card.doc} className="rounded-xl border border-dashed p-5 opacity-70 flex flex-col gap-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="rounded-lg bg-muted p-2.5">
                      <Icon className="w-5 h-5 text-muted-foreground" />
                    </div>
                    <div>
                      <h3 className="font-semibold">{card.title}</h3>
                      <p className="text-xs text-muted-foreground">{card.sagePath}</p>
                    </div>
                  </div>
                  <Badge variant="outline" className="gap-1">
                    <Lock className="w-3 h-3" /> In Sage
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground">{card.what}</p>
              </div>
            );
          }
          const doc = card.doc;
          const info = plan?.docs[doc];
          const reason = blockedReason(doc, info);
          const isSel = selected === doc;
          return (
            <div
              key={doc}
              className={`rounded-xl border p-5 flex flex-col gap-3 transition-colors cursor-pointer ${
                isSel ? "border-primary ring-1 ring-primary/40 bg-primary/5" : "hover:border-primary/50"
              }`}
              onClick={() => setSelected(doc)}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-3">
                  <div className="rounded-lg bg-primary/10 p-2.5">
                    <Icon className="w-5 h-5 text-primary" />
                  </div>
                  <div>
                    <h3 className="font-semibold leading-tight">{card.title}</h3>
                    <p className="text-xs text-muted-foreground">{card.sagePath}</p>
                  </div>
                </div>
                <Badge variant="secondary" className="shrink-0 whitespace-nowrap" title="Import order in Sage">
                  Step {card.step}
                </Badge>
              </div>

              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-bold">{info?.records ?? "–"}</span>
                <span className="text-sm text-muted-foreground">{card.unit} ready</span>
                {!!info?.total && <span className="ml-auto text-sm font-medium">{naira(info.total)}</span>}
              </div>

              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span className="font-mono">{info?.file_name}</span>
                {info && (
                  <span>
                    {info.columns.length}/{info.headers.length} columns
                  </span>
                )}
                {!!info?.blocked && <span className="text-warning">{info.blocked} held back</span>}
                <span>
                  Last export:{" "}
                  {info?.last_exported ? format(new Date(info.last_exported), "d MMM, HH:mm") : "never"}
                </span>
              </div>

              <div className="mt-auto flex items-center gap-2 pt-1">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelected(doc);
                    document.getElementById("sage-doc-detail")?.scrollIntoView({ behavior: "smooth" });
                  }}
                >
                  <Eye className="w-4 h-4 mr-1.5" /> View
                </Button>
                <Button
                  size="sm"
                  className="flex-1"
                  variant={reason ? "outline" : "default"}
                  disabled={!!reason || exporting !== null}
                  onClick={(e) => {
                    e.stopPropagation();
                    exportDoc(doc);
                  }}
                >
                  <FolderDown className="w-4 h-4 mr-1.5" />
                  {exporting === doc ? "Exporting…" : `Export ${info?.file_name ?? ""}`}
                </Button>
              </div>
              {reason && <p className="text-xs text-muted-foreground -mt-1">{reason}</p>}
            </div>
          );
        })}
      </div>

      {/* ── Selected document: data / columns / held back ────────────────── */}
      {selectedInfo && (
        <div id="sage-doc-detail" className="pw-surface-interactive rounded-xl border overflow-hidden">
          <div className="px-5 py-4 border-b flex flex-wrap items-center gap-3">
            <selectedCard.icon className="w-5 h-5 text-primary" />
            <div>
              <h3 className="font-semibold">
                {selectedCard.title} <span className="font-mono text-sm text-muted-foreground">· {selectedInfo.file_name}</span>
              </h3>
              <p className="text-xs text-muted-foreground">{selectedCard.what}</p>
            </div>
          </div>
          <Tabs defaultValue="data" className="p-5">
            <TabsList>
              <TabsTrigger value="data">Data preview ({selectedInfo.rows} rows)</TabsTrigger>
              <TabsTrigger value="columns">
                Columns ({selectedInfo.columns.length}/{selectedInfo.headers.length})
              </TabsTrigger>
              <TabsTrigger value="held">Held back ({selectedInfo.blocked})</TabsTrigger>
            </TabsList>
            <TabsContent value="data" className="mt-4">
              <DataPreview info={selectedInfo} />
            </TabsContent>
            <TabsContent value="columns" className="mt-4">
              <ColumnPicker
                doc={selected}
                info={selectedInfo}
                settings={settings.data}
                onSaved={refreshAll}
              />
            </TabsContent>
            <TabsContent value="held" className="mt-4">
              <HeldBack items={plan!.blocked.filter((b) => b.doc_type === selected)} />
            </TabsContent>
          </Tabs>
        </div>
      )}

      {/* ── How to import ───────────────────────────────────────────────── */}
      <div className="rounded-xl border bg-info/5 border-info/30 p-5 space-y-2">
        <h3 className="font-semibold flex items-center gap-2">
          <Info className="w-4 h-4 text-info" /> Importing into Sage
        </h3>
        <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-warning" />
          <span>
            Every file starts with a heading row. In Sage's Import window, on the <strong>Options</strong> tab,
            tick <strong>First Row Contains Headings</strong> — otherwise Sage reads the headings as data and
            stops with <em>"Line Number: 1 … The process cannot continue"</em> (nothing is posted).
          </span>
        </div>
        <ol className="text-sm space-y-1 list-decimal pl-5 text-muted-foreground">
          <li>Back up the Sage company, and post this period's supplier bills in Sage first.</li>
          <li>
            Import in step order: Customer List → Sales Journal → Cash Receipts → Adjustments.
          </li>
          <li>
            In Sage: <strong>File → Select Import/Export</strong> → pick the template → <strong>Import</strong>.
            On the Options tab, browse to the file (e.g. <span className="font-mono">Documents\SALES.CSV</span>)
            and tick <strong>First Row Contains Headings</strong>.
          </li>
          <li>
            Afterwards, re-import Aged Receivables on the Import tab so ACE sees the new invoices as open.
            Never key the same invoices or receipts into Sage by hand.
          </li>
        </ol>
      </div>

      {/* ── History ─────────────────────────────────────────────────────── */}
      <div className="pw-surface-interactive rounded-xl border overflow-hidden">
        <div className="px-5 py-4 border-b">
          <h3 className="font-semibold">Exported files</h3>
        </div>
        {!batches.data?.batches?.length ? (
          <p className="px-5 py-4 text-sm text-muted-foreground">Nothing exported yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Exported</TableHead>
                <TableHead>File</TableHead>
                <TableHead>Records</TableHead>
                <TableHead>Period</TableHead>
                <TableHead>By</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {batches.data.batches.flatMap((b) =>
                (b.files ?? []).map((f, i) => {
                  const doc = FILE_DOC[f];
                  const c = doc ? b.counts?.[doc] : undefined;
                  return (
                    <TableRow key={`${b.id}-${f}`}>
                      <TableCell className="text-sm">{format(new Date(b.created_at), "d MMM yyyy, HH:mm")}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className="font-mono">{f}</Badge>
                      </TableCell>
                      <TableCell className="text-sm">
                        {c ? `${c.records}${c.total ? ` · ${naira(c.total)}` : ""}` : "—"}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {b.period_from} → {b.period_to}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">{b.created_by ?? "—"}</TableCell>
                      <TableCell className="text-right space-x-1">
                        <Button size="sm" variant="outline" onClick={() => redownload(b.id, f)} title="Save again">
                          <Download className="w-3.5 h-3.5" />
                        </Button>
                        {i === 0 && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => removeBatch(b.id)}
                            title="Undo export (only if NOT imported into Sage)"
                          >
                            <Trash2 className="w-3.5 h-3.5 text-destructive" />
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                }),
              )}
            </TableBody>
          </Table>
        )}
      </div>

      <ExportSettingsSheet open={settingsOpen} onOpenChange={setSettingsOpen} onSaved={refreshAll} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Data preview — the rows exactly as they'll land in the CSV
// ---------------------------------------------------------------------------

function DataPreview({ info }: { info: SageExportDocInfo }) {
  // Show only what ACE actually fills; the CSV still carries every selected
  // column (blank, or the fixed value Sage's template always has).
  const ace = new Set(info.ace_fields);
  const filled = info.columns
    .filter((c) => ace.has(c))
    .map((c) => info.headers.indexOf(c));
  if (!info.preview_rows.length)
    return <p className="text-sm text-muted-foreground">No rows to export for this period.</p>;
  return (
    <div className="space-y-2">
      <div className="overflow-auto max-h-[420px] rounded-lg border">
        <table className="text-xs whitespace-nowrap">
          <thead className="sticky top-0 bg-muted">
            <tr>
              {filled.map((i) => (
                <th key={i} className="px-3 py-2 text-left font-medium">
                  {info.headers[i]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {info.preview_rows.map((r, ri) => (
              <tr key={ri} className="border-t">
                {filled.map((i) => (
                  <td
                    key={i}
                    className={`px-3 py-1.5 ${/^-?\d+(\.\d+)?$/.test(r[i] ?? "") ? "text-right font-mono" : ""}`}
                  >
                    {r[i]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Showing {info.preview_rows.length} of {info.rows} rows and the {filled.length} columns ACE fills.
        The file also carries the other {info.columns.length - filled.length} selected columns, blank or
        with Sage's standard values (see Columns). Credit amounts are negative, as Sage expects.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Column picker — mirrors Sage's Import/Export "Fields" tab
// ---------------------------------------------------------------------------

function ColumnPicker({
  doc,
  info,
  settings,
  onSaved,
}: {
  doc: SageExportDoc;
  info: SageExportDocInfo;
  settings?: SageExportSettings;
  onSaved: () => void;
}) {
  const [chosen, setChosen] = useState<Set<string>>(new Set(info.columns));
  const [saving, setSaving] = useState(false);
  useEffect(() => setChosen(new Set(info.columns)), [doc, info.columns]);

  const required = useMemo(() => new Set(info.required), [info.required]);
  const aceFills = useMemo(() => new Set(info.ace_fields), [info.ace_fields]);
  const dirty =
    chosen.size !== info.columns.length || info.columns.some((c) => !chosen.has(c));

  const toggle = (c: string) =>
    setChosen((s) => {
      const n = new Set(s);
      n.has(c) ? n.delete(c) : n.add(c);
      return n;
    });

  const save = async () => {
    setSaving(true);
    try {
      const all = chosen.size === info.headers.length;
      await api.sageExport.saveSettings({
        column_selection: {
          ...(settings?.column_selection ?? {}),
          // All columns = no selection stored (matches the Sage template as exported).
          [doc]: all ? [] : info.headers.filter((h) => chosen.has(h)),
        },
      });
      toast.success("Column layout saved");
      onSaved();
    } catch (e: any) {
      toast.error(e?.message ?? "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2 rounded-lg bg-warning/10 text-sm px-3 py-2">
        <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-warning" />
        <span>
          Sage reads columns by position. Whatever you untick here, untick the same fields (the{" "}
          <strong>Show</strong> box) on the <strong>Fields</strong> tab of Sage's{" "}
          {info.file_name.replace(".CSV", "").toLowerCase()} import template. Leaving everything ticked
          matches the template exactly as it was exported from Sage.
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" onClick={() => setChosen(new Set(info.headers))}>
          Show all ({info.headers.length})
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setChosen(new Set([...info.headers.filter((h) => aceFills.has(h) || required.has(h))]))}
          disabled={!info.ace_fields.length}
        >
          Only fields ACE fills
        </Button>
        <span className="text-sm text-muted-foreground">
          {chosen.size} of {info.headers.length} shown
        </span>
        <Button size="sm" className="ml-auto" onClick={save} disabled={!dirty || saving}>
          <Columns3 className="w-4 h-4 mr-1.5" /> {saving ? "Saving…" : "Save column layout"}
        </Button>
      </div>
      <div className="rounded-lg border max-h-[420px] overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-muted">
            <tr>
              <th className="px-3 py-2 w-10 text-left">#</th>
              <th className="px-3 py-2 text-left">Field</th>
              <th className="px-3 py-2 w-20 text-center">Show</th>
              <th className="px-3 py-2 text-left">Notes</th>
            </tr>
          </thead>
          <tbody>
            {info.headers.map((h, i) => (
              <tr key={h} className="border-t">
                <td className="px-3 py-1.5 text-muted-foreground">{i + 1}</td>
                <td className="px-3 py-1.5">{h}</td>
                <td className="px-3 py-1.5 text-center">
                  <Checkbox
                    checked={required.has(h) || chosen.has(h)}
                    disabled={required.has(h)}
                    onCheckedChange={() => toggle(h)}
                    aria-label={`Show ${h}`}
                  />
                </td>
                <td className="px-3 py-1.5 text-xs">
                  {required.has(h) ? (
                    <Badge variant="secondary" className="gap-1">
                      <Lock className="w-3 h-3" /> Required by Sage
                    </Badge>
                  ) : aceFills.has(h) ? (
                    <span className="text-success">Filled by ACE</span>
                  ) : info.defaults[h] !== undefined ? (
                    <span className="text-muted-foreground">
                      Sage standard value: <span className="font-mono">{info.defaults[h]}</span>
                    </span>
                  ) : (
                    <span className="text-muted-foreground">Left blank</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function HeldBack({ items }: { items: { ref: string; reason: string; fix: string; source_id: string }[] }) {
  if (!items.length)
    return (
      <p className="text-sm text-muted-foreground flex items-center gap-2">
        <CheckCircle2 className="w-4 h-4 text-success" /> Nothing held back.
      </p>
    );
  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground">
        These aren't in the file. ACE never sends half a transaction — fix them in ACE and they'll
        appear in the next export.
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Reference</TableHead>
            <TableHead>Why</TableHead>
            <TableHead>How to fix</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((b) => (
            <TableRow key={b.source_id}>
              <TableCell className="font-mono text-xs">{b.ref}</TableCell>
              <TableCell className="text-sm">{b.reason}</TableCell>
              <TableCell className="text-sm text-muted-foreground">{b.fix || "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

function ExportSettingsSheet({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<SageExportSettings | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    api.sageExport
      .settings()
      .then(setDraft)
      .catch((e) => toast.error(e.message));
  }, [open]);

  const set = <K extends keyof SageExportSettings>(k: K, v: SageExportSettings[K]) =>
    setDraft((d) => (d ? { ...d, [k]: v } : d));
  const setMethod = (m: string, field: "method" | "cash_account" | "reference", v: string) =>
    setDraft((d) =>
      d
        ? {
            ...d,
            payment_method_map: { ...d.payment_method_map, [m]: { ...d.payment_method_map[m], [field]: v } },
          }
        : d,
    );

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      await api.sageExport.saveSettings({
        cutover_date: draft.cutover_date || null,
        sage_open_until: draft.sage_open_until || null,
        ar_account: draft.ar_account,
        writeoff_gl_account: draft.writeoff_gl_account || null,
        payment_method_map: draft.payment_method_map,
      });
      toast.success("Export settings saved");
      onSaved();
      onOpenChange(false);
    } catch (e: any) {
      toast.error(e?.message ?? "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <DetailSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Export settings"
      description="Agree these with the accountant once. They decide which Sage accounts the files post to."
      icon={Settings2}
      footer={
        <Button onClick={save} disabled={!draft || saving}>
          {saving ? "Saving…" : "Save settings"}
        </Button>
      }
    >
      {!draft ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <>
          <div className="space-y-1">
            <Label htmlFor="sx-cutover">Cut-over date</Label>
            <Input
              id="sx-cutover"
              type="date"
              value={draft.cutover_date ?? ""}
              onChange={(e) => set("cutover_date", e.target.value || null)}
            />
            <p className="text-xs text-muted-foreground">
              From this date invoices and receipts are raised in ACE only. Earlier ones are never
              exported — they're already in Sage.
            </p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="sx-open">Sage open up to</Label>
            <Input
              id="sx-open"
              type="date"
              value={draft.sage_open_until ?? ""}
              onChange={(e) => set("sage_open_until", e.target.value || null)}
            />
            <p className="text-xs text-muted-foreground">
              The last day of the newest fiscal year open in Sage. Sage refuses anything dated later
              ("Field Name: Date"), so ACE holds those records back until the accountant opens the
              next year and updates this date.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="sx-ar">Accounts Receivable account</Label>
              <Input id="sx-ar" value={draft.ar_account} onChange={(e) => set("ar_account", e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="sx-wo">Stock write-off account</Label>
              <Input
                id="sx-wo"
                placeholder="e.g. 58500 Inventory Adjustments"
                value={draft.writeoff_gl_account ?? ""}
                onChange={(e) => set("writeoff_gl_account", e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label>Payment methods → Sage</Label>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ACE method</TableHead>
                  <TableHead>Sage method</TableHead>
                  <TableHead>Cash account</TableHead>
                  <TableHead>Reference</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(draft.payment_method_map).map(([m, v]) => (
                  <TableRow key={m}>
                    <TableCell className="text-xs font-mono">{m}</TableCell>
                    <TableCell>
                      <select
                        className="h-8 rounded-md border bg-background px-2 text-sm"
                        value={v.method}
                        onChange={(e) => setMethod(m, "method", e.target.value)}
                      >
                        <option>Check</option>
                        <option>Cash</option>
                      </select>
                    </TableCell>
                    <TableCell>
                      <Input
                        className="h-8"
                        value={v.cash_account}
                        onChange={(e) => setMethod(m, "cash_account", e.target.value)}
                      />
                    </TableCell>
                    <TableCell>
                      <Input
                        className="h-8"
                        value={v.reference}
                        onChange={(e) => setMethod(m, "reference", e.target.value)}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <p className="text-xs text-muted-foreground">
              10100 Cash on Hand · 10290 Fidelity Bank · 10260 GTB · 10200 Zenith
            </p>
          </div>
        </>
      )}
    </DetailSheet>
  );
}
