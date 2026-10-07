/**
 * Generate a report - the one sequence used everywhere in ACE:
 *   1. what kind of report            (deviation, recall, sales, stock, P&L ...)
 *   2. about exactly what             (the deviation, the sale, the customer, the product, the month ...)
 *   3. review what ACE gathered       (every fact from the module that owns the record; add notes)
 *   4. generate                       (written only from that record, with the record attached as the appendix)
 * Pages across the app deep-link straight to step 3: /reports/new?type=deviation&kind=deviation&id=...
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowLeft, ArrowUpRight, CheckCircle2, ChevronRight, Download, FileText, History, Loader2, Search, Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/workspace/PageHeader";
import { Md } from "@/components/reports/Md";
import { api } from "@/lib/api-client";

type Dict = Record<string, any>;
const fmt = (v?: string | null) => (v ? new Date(v.length <= 10 ? v + "T12:00:00" : v).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "");

function Steps({ step }: { step: number }) {
  const labels = ["Report type", "Choose the record", "Review the information", "Report"];
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      {labels.map((l, i) => (
        <span key={l} className="flex items-center gap-2">
          <span className={`flex h-6 items-center gap-1.5 rounded-full px-2.5 ${i + 1 === step ? "bg-primary text-primary-foreground" : i + 1 < step ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"}`}>
            {i + 1 < step ? <CheckCircle2 className="h-3.5 w-3.5" /> : <span className="font-semibold">{i + 1}</span>}{l}
          </span>
          {i < labels.length - 1 && <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
        </span>
      ))}
    </div>
  );
}

export default function ReportComposer() {
  const [params, setParams] = useSearchParams();
  const type = params.get("type") || "";
  const kind = params.get("kind") || "";
  const id = params.get("id") || "";
  const [search, setSearch] = useState("");
  const [notes, setNotes] = useState("");
  const [result, setResult] = useState<Dict | null>(null);
  const [busy, setBusy] = useState(false);
  const [approving, setApproving] = useState(false);

  const cat = useQuery({ queryKey: ["reports", "catalog"], queryFn: () => api.reports.catalog(), staleTime: 600_000 });
  const t = (cat.data?.types ?? []).find((x: Dict) => x.type === type);
  const activeKind = kind || t?.kinds?.[0] || "";
  const subjects = useQuery({ queryKey: ["reports", "subjects", activeKind, search], queryFn: () => api.reports.subjects(activeKind, search),
    enabled: !!t && !id && !!activeKind });
  const dossier = useQuery({ queryKey: ["reports", "dossier", type, kind, id], queryFn: () => api.reports.dossier(type, kind, id),
    enabled: !!type && !!kind && !!id && !result });
  const prior = useQuery({ queryKey: ["reports", "for", kind, id], queryFn: () => api.reports.forRecord(kind, id), enabled: !!kind && !!id });
  useEffect(() => { setResult(null); setNotes(""); }, [type, kind, id]);

  const go = (p: Record<string, string>) => setParams(Object.fromEntries(Object.entries(p).filter(([, v]) => v)), { replace: false });
  const step = result ? 4 : id ? 3 : type ? 2 : 1;
  const groups = useMemo(() => {
    const g: Record<string, Dict[]> = {};
    for (const x of cat.data?.types ?? []) (g[x.group] ??= []).push(x);
    return g;
  }, [cat.data]);

  const generate = async () => {
    setBusy(true);
    try { setResult(await api.reports.fromRecord({ report_type: type, kind, id, notes: notes.trim() || undefined })); prior.refetch(); }
    catch (e: any) { toast.error(e?.message || "Report generation failed"); } finally { setBusy(false); }
  };
  const download = async (rid: string) => {
    try {
      const { url, filename } = await api.reports.downloadDocx(rid);
      const a = document.createElement("a"); a.href = url; a.download = filename; a.click();
    } catch (e: any) { toast.error(e?.message || "Download failed"); }
  };
  const approve = async () => {
    setApproving(true);
    try { await api.reports.approve(result!.report_memory_id); toast.success("Report approved - marked FINAL"); setResult({ ...result!, approved: true }); }
    catch (e: any) { toast.error(e?.message || "Approval failed"); } finally { setApproving(false); }
  };

  const d = dossier.data;
  return (
    <div className="flex flex-col gap-5">
      <PageHeader icon={FileText} title="Generate a report"
        subtitle="Choose exactly what the report is about. ACE gathers everything recorded on it, you review, then the report is written from that record only."
        actions={<Link to="/reports"><Button variant="outline" size="sm"><History className="mr-1.5 h-4 w-4" />Report library</Button></Link>} />
      <Steps step={step} />

      {/* 1. type */}
      {step === 1 && (cat.isLoading ? <Loader2 className="mx-auto h-6 w-6 animate-spin" /> : (
        <div className="space-y-5">
          {Object.entries(groups).map(([g, items]) => (
            <div key={g}>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{g}</div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {items.map((x) => (
                  <button key={x.type} onClick={() => go({ type: x.type })} className="rounded-xl border bg-card p-4 text-left transition-colors hover:border-primary/50">
                    <div className="font-medium">{x.name}</div>
                    <div className="mt-1 text-xs text-muted-foreground">{x.about}</div>
                    <div className="mt-2 flex flex-wrap gap-1">{x.kinds.map((k: string) => <Badge key={k} variant="secondary" className="text-[10px]">on {cat.data?.kind_labels?.[k]}</Badge>)}</div>
                  </button>
                ))}
              </div>
            </div>
          ))}
          <p className="text-xs text-muted-foreground">Need an invoice document or the older date-range report? <Link to="/reports/classic" className="text-primary hover:underline">Classic report builder</Link></p>
        </div>
      ))}

      {/* 2. choose the record */}
      {step === 2 && t && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => go({})}><ArrowLeft className="mr-1 h-4 w-4" />Report types</Button>
            <span className="font-medium">{t.name}</span>
            <span className="text-sm text-muted-foreground">- about which {t.kinds.length > 1 ? "record" : cat.data?.kind_labels?.[activeKind]?.replace(/^an? /, "")}?</span>
          </div>
          {t.kinds.length > 1 && (
            <div className="flex gap-1 rounded-lg bg-muted p-1 text-sm">
              {t.kinds.map((k: string) => (
                <button key={k} onClick={() => go({ type, kind: k })} className={`rounded-md px-3 py-1 capitalize ${activeKind === k ? "bg-background font-medium shadow-sm" : "text-muted-foreground"}`}>
                  {cat.data?.kind_labels?.[k]?.replace(/^an? /, "")}</button>
              ))}
            </div>
          )}
          <div className="relative max-w-md"><Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input className="pl-8" placeholder="Search by number, name, product, customer…" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
          {subjects.isLoading ? <Loader2 className="mx-auto h-5 w-5 animate-spin" /> : (subjects.data?.items ?? []).length === 0 ? (
            <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">No {cat.data?.kind_labels?.[activeKind]?.replace(/^an? /, "")} records found{search ? " for that search" : ""}.</p>
          ) : (
            <div className="divide-y rounded-xl border bg-card">
              {subjects.data!.items.map((s: Dict) => (
                <button key={s.id} onClick={() => go({ type, kind: activeKind, id: s.id })} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/40">
                  <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{s.title}</div><div className="truncate text-xs text-muted-foreground">{s.subtitle}</div></div>
                  {s.status && <Badge variant="outline" className="shrink-0 capitalize">{String(s.status).replace(/_/g, " ")}</Badge>}
                  <span className="w-24 shrink-0 text-right text-xs text-muted-foreground">{fmt(s.date)}</span>
                  <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 3. review */}
      {step === 3 && (
        dossier.isLoading ? <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin" />Gathering everything recorded on it…</div> :
          dossier.error ? <p className="text-sm text-destructive">{(dossier.error as any)?.message}</p> : d && (
            <div className="grid gap-4 xl:grid-cols-3">
              <div className="space-y-4 xl:col-span-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="ghost" size="sm" onClick={() => go({ type, kind })}><ArrowLeft className="mr-1 h-4 w-4" />Choose another</Button>
                  <div><div className="font-semibold">{d.title}</div><div className="text-xs text-muted-foreground">{t?.name} · {d.subtitle}</div></div>
                  {(d.links ?? []).map((l: Dict) => <Link key={l.href} to={l.href} className="ml-auto flex items-center text-xs text-primary hover:underline">{l.label}<ArrowUpRight className="h-3 w-3" /></Link>)}
                </div>
                <section className="rounded-xl border bg-card p-4">
                  <h3 className="mb-2 text-sm font-semibold">What ACE found</h3>
                  <dl className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
                    {d.facts.map((f: Dict) => (
                      <div key={f.label} className="flex justify-between gap-3 border-b border-dashed py-1">
                        <dt className="text-muted-foreground">{f.label}</dt>
                        <dd className={`text-right font-medium ${f.value === "not recorded" ? "text-amber-600" : ""} ${String(f.value).includes("OVERDUE") ? "text-red-600" : ""}`}>{f.value}</dd>
                      </div>
                    ))}
                  </dl>
                  {d.texts.map((x: Dict) => <div key={x.label} className="mt-3 text-sm"><div className="text-xs font-semibold text-muted-foreground">{x.label}</div><p className="whitespace-pre-wrap">{x.value}</p></div>)}
                </section>
                {d.tables.map((tb: Dict) => (
                  <section key={tb.title} className="rounded-xl border bg-card p-4">
                    <h3 className="mb-2 text-sm font-semibold">{tb.title} <span className="font-normal text-muted-foreground">· {tb.rows.length}</span></h3>
                    <div className="max-h-72 overflow-auto">
                      <table className="w-full text-xs">
                        <thead className="sticky top-0 bg-card"><tr className="border-b">{tb.columns.map((c: string) => <th key={c} className="py-1.5 pr-3 text-left font-medium text-muted-foreground">{c}</th>)}</tr></thead>
                        <tbody className="divide-y">{tb.rows.map((r: any[], i: number) => <tr key={i}>{r.map((c, j) => <td key={j} className="py-1 pr-3 align-top">{c}</td>)}</tr>)}</tbody>
                      </table>
                    </div>
                  </section>
                ))}
              </div>
              <div className="space-y-4">
                {d.gaps.length > 0 && (
                  <section className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm dark:border-amber-500/40 dark:bg-amber-500/10">
                    <h3 className="mb-1 flex items-center gap-1.5 font-semibold"><AlertTriangle className="h-4 w-4 text-amber-600" />Not recorded in the system</h3>
                    <ul className="list-disc space-y-0.5 pl-5 text-xs">{d.gaps.map((g: string) => <li key={g}>{g}</li>)}</ul>
                    <p className="mt-2 text-xs text-muted-foreground">The report will say these are missing rather than guess. To include them, add them on the record first{d.links?.[0] ? <> (<Link className="text-primary hover:underline" to={d.links[0].href}>open it</Link>)</> : ""}, or write them in the notes below.</p>
                  </section>
                )}
                <section className="rounded-xl border bg-card p-4">
                  <h3 className="mb-2 text-sm font-semibold">The report will cover</h3>
                  <ol className="list-decimal space-y-0.5 pl-5 text-sm">{d.sections.map((s: string) => <li key={s}>{s}</li>)}<li>Appendix: the record details above</li></ol>
                </section>
                <section className="rounded-xl border bg-card p-4">
                  <h3 className="mb-2 text-sm font-semibold">Your notes (optional)</h3>
                  <Textarea rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Context the record doesn't hold - e.g. what you observed, who you spoke to, what the report is for." />
                  <Button className="mt-3 w-full" disabled={busy} onClick={generate}>
                    {busy ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Writing the report…</> : <><Sparkles className="mr-2 h-4 w-4" />Generate report</>}
                  </Button>
                  <p className="mt-2 text-[11px] text-muted-foreground">Written only from the information on this page. Nothing is sent to the record.</p>
                </section>
                {(prior.data?.reports ?? []).length > 0 && (
                  <section className="rounded-xl border bg-card p-4">
                    <h3 className="mb-2 text-sm font-semibold">Reports already written on this</h3>
                    {prior.data!.reports.map((r: Dict) => (
                      <button key={r.id} onClick={() => download(r.id)} className="flex w-full items-center justify-between gap-2 py-1 text-left text-xs hover:text-primary">
                        <span>{fmt(r.created_at)} · {r.approval_status === "approved" ? "final" : "draft"}</span><Download className="h-3.5 w-3.5" />
                      </button>
                    ))}
                  </section>
                )}
              </div>
            </div>
          ))}

      {/* 4. result */}
      {step === 4 && result && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="mr-auto"><div className="font-semibold">{result.section_title}</div>
              <div className="text-xs text-muted-foreground">Quality check {result.quality_score?.toFixed?.(1) ?? "—"}/10 · {result.approved ? "FINAL" : "draft"}</div></div>
            <Button variant="outline" size="sm" onClick={() => setResult(null)}><ArrowLeft className="mr-1 h-4 w-4" />Back to the information</Button>
            <Button variant="outline" size="sm" onClick={() => download(result.report_memory_id)}><Download className="mr-1.5 h-4 w-4" />Download Word</Button>
            <Button size="sm" disabled={approving || result.approved} onClick={approve}><CheckCircle2 className="mr-1.5 h-4 w-4" />{result.approved ? "Approved" : "Approve as final"}</Button>
          </div>
          <article className="rounded-xl border bg-card p-6"><Md text={result.full_report} /></article>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => go({ type, kind })}>Another {t?.name?.toLowerCase()}</Button>
            <Link to="/reports"><Button variant="ghost">Report library</Button></Link>
          </div>
        </div>
      )}
    </div>
  );
}
