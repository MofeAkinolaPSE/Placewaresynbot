/**
 * The General Ledger in Sage's layout, over the Sage years and ACE Books alike:
 *   Account ID | Account Description | Date | Reference | Jrnl | Trans Description | Debit Amt | Credit Amt | Balance
 * per account, per month: Beginning Balance, every transaction, Current Period Change; then the
 * Ending Balance. Every line opens what is behind it (the invoice, the receipt, every line of the
 * transaction, the ACE Books journal).
 */
import { Fragment, useState } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dict, fmtDate } from "@/lib/books-api";
import { sageLineTarget, sourceTarget, DrillTarget } from "./drill-context";
import { Amount, CsvButton, DrillLink, ErrorNote, Loading, useBooks } from "./kit";

export function lineTarget(l: Dict): DrillTarget | null {
  if (l.source === "sage") return sageLineTarget(l as any);
  return sourceTarget(l.source_type, l.source_id) ?? (l.journal_id ? { type: "journal", id: l.journal_id, label: l.journal_number } : null);
}

export function glCsvRows(d: Dict | undefined): Dict[] {
  if (!d) return [];
  const a = d.account;
  const out: Dict[] = [];
  for (const m of d.months) {
    out.push({ account_id: a.code, account_description: a.name, date: m.period_start, reference: "", jrnl: "", trans_description: "Beginning Balance", debit: "", credit: "", balance: m.beginning_balance });
    for (const l of m.lines) out.push({ account_id: a.code, account_description: a.name, date: l.date, reference: l.reference ?? "", jrnl: l.jrnl ?? "", trans_description: l.description ?? "", debit: Number(l.debit) || "", credit: Number(l.credit) || "", balance: "" });
    out.push({ account_id: a.code, account_description: a.name, date: "", reference: "", jrnl: "", trans_description: "Current Period Change", debit: m.period_debit, credit: m.period_credit, balance: m.net_change });
  }
  out.push({ account_id: a.code, account_description: a.name, date: d.date_to, reference: "", jrnl: "", trans_description: "Ending Balance", debit: "", credit: "", balance: d.closing });
  return out;
}

export const GL_COLUMNS = [
  { key: "account_id", label: "Account ID" }, { key: "account_description", label: "Account Description" }, { key: "date", label: "Date" },
  { key: "reference", label: "Reference" }, { key: "jrnl", label: "Jrnl" }, { key: "trans_description", label: "Trans Description" },
  { key: "debit", label: "Debit Amt" }, { key: "credit", label: "Credit Amt" }, { key: "balance", label: "Balance" },
];

/** One account's detail for a period (fetched when shown). */
export function GlAccountDetail({ code, from, to, compact }: { code: string; from: string; to: string; compact?: boolean }) {
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const { data, isLoading, error } = useBooks<Dict>(["gl-account", code, from, to, q], `/ledger/gl-account/${encodeURIComponent(code)}`,
    { from, to, search: q || undefined });
  if (isLoading) return <Loading />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;
  const lines = data.months.reduce((s: number, m: Dict) => s + m.lines.length, 0);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="relative w-64"><Search className="absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
          <Input className="h-8 pl-7 text-xs" placeholder="Search reference / description (Enter)" value={search}
                 onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && setQ(search.trim())} /></div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>{lines.toLocaleString()} line{lines === 1 ? "" : "s"}</span>
          <CsvButton filename={`general-ledger-${code}-${from}-${to}.csv`} rows={glCsvRows(data)} columns={GL_COLUMNS} />
        </div>
      </div>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader><TableRow>
            <TableHead className="w-24">Date</TableHead><TableHead className="w-32">Reference</TableHead><TableHead className="w-14">Jrnl</TableHead>
            <TableHead>Trans Description</TableHead><TableHead className="text-right">Debit Amt</TableHead><TableHead className="text-right">Credit Amt</TableHead>
            <TableHead className="text-right">Balance</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {data.months.map((m: Dict) => (
              <Fragment key={m.period_start}>
                <TableRow className="bg-muted/40">
                  <TableCell className="whitespace-nowrap text-xs">{fmtDate(m.period_start)}</TableCell><TableCell /><TableCell />
                  <TableCell className="text-xs font-medium">Beginning Balance</TableCell><TableCell /><TableCell />
                  <TableCell className="text-right text-xs font-medium"><Amount value={m.beginning_balance} /></TableCell>
                </TableRow>
                {m.lines.map((l: Dict, i: number) => {
                  const t = lineTarget(l);
                  return (
                    <TableRow key={`${m.period_start}-${i}`} className={compact ? "text-xs" : ""}>
                      <TableCell className="whitespace-nowrap text-xs">{fmtDate(l.date)}</TableCell>
                      <TableCell className="font-mono text-xs">{t ? <DrillLink to={t}>{l.reference || "—"}</DrillLink> : l.reference}</TableCell>
                      <TableCell className="text-xs">{l.jrnl}</TableCell>
                      <TableCell className="max-w-[420px] text-xs">{l.description}</TableCell>
                      <TableCell className="text-right"><Amount value={l.debit} blankZero /></TableCell>
                      <TableCell className="text-right"><Amount value={l.credit} blankZero /></TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground">{q ? "" : <Amount value={l.balance} />}</TableCell>
                    </TableRow>
                  );
                })}
                <TableRow className="border-b-2">
                  <TableCell /><TableCell /><TableCell />
                  <TableCell className="text-xs font-medium">Current Period Change</TableCell>
                  <TableCell className="text-right text-xs font-medium"><Amount value={m.period_debit} blankZero /></TableCell>
                  <TableCell className="text-right text-xs font-medium"><Amount value={m.period_credit} blankZero /></TableCell>
                  <TableCell className="text-right text-xs font-medium"><Amount value={m.net_change} /></TableCell>
                </TableRow>
              </Fragment>
            ))}
            <TableRow className="font-semibold">
              <TableCell className="whitespace-nowrap text-xs">{fmtDate(data.date_to)}</TableCell><TableCell /><TableCell />
              <TableCell className="text-xs">Ending Balance</TableCell>
              <TableCell className="text-right"><Amount value={data.total_debit} /></TableCell><TableCell className="text-right"><Amount value={data.total_credit} /></TableCell>
              <TableCell className="text-right"><Amount value={data.closing} bold /></TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
