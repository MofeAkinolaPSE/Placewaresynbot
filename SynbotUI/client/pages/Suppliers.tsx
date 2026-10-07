/**
 * Operations › Suppliers.
 *
 * Every figure comes from ACE Books: what we owe (payables, netted as on the
 * Payables screen), what we buy and how often (the Sage purchase journal to the
 * cut-over + ACE Books supplier bills after it), and the price trend on the items
 * each supplier sells us. The old page read delivery-scorecard tables that were
 * never populated, so every "Metrics" click failed.
 */
import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, PlusCircle, ShoppingCart, TruckIcon, Users, Wallet } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/workspace/PageHeader";
import { KpiStrip } from "@/components/workspace/KpiStrip";
import { DetailSheet } from "@/components/workspace/DetailSheet";
import { motionTransitions } from "@/lib/motion";
import { api } from "@/lib/api-client";
import { Dict, fmtDate, naira, num } from "@/lib/books-api";
import { DrillProvider, Facts, RecordView } from "@/components/books/lineage";
import { useAuth } from "@/components/AuthProvider";

const BLANK = { name: "", contact_name: "", contact_email: "", phone: "", address: "", payment_terms: "Net 30 Days", tax_id: "", bank_details: "" };
const FILTERS: [string, string][] = [["active", "Bought from in the last 12 months"], ["balance", "We owe"], ["all", "All suppliers"]];

export default function Suppliers() {
  return (
    <DrillProvider>
      <SuppliersPage />
    </DrillProvider>
  );
}

function SuppliersPage() {
  const qc = useQueryClient();
  const { roles } = useAuth();
  const { data, isLoading } = useQuery({ queryKey: ["supplier-directory"], queryFn: () => api.procurement.supplierDirectory() });
  const [filter, setFilter] = useState("active");
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<Dict | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState(BLANK);
  const [saving, setSaving] = useState(false);
  const t = data?.totals;
  const all: Dict[] = data?.suppliers ?? [];
  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return all.filter((s) => {
      if (filter === "active" && !s.active) return false;
      if (filter === "balance" && !(s.balance > 0)) return false;
      return !q || `${s.name} ${s.code ?? ""} ${s.contact_name ?? ""}`.toLowerCase().includes(q);
    });
  }, [all, filter, search]);

  const create = async () => {
    if (!form.name.trim()) return toast.error("Supplier name is required");
    setSaving(true);
    try {
      await api.suppliers.create(Object.fromEntries(Object.entries(form).filter(([, v]) => v !== "")));
      toast.success(`${form.name} added`);
      setAdding(false);
      setForm(BLANK);
      qc.invalidateQueries({ queryKey: ["supplier-directory"] });
    } catch (e: any) {
      toast.error(e.message ?? "Could not add the supplier");
    } finally {
      setSaving(false);
    }
  };

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={motionTransitions.standard} className="space-y-5">
      <PageHeader
        icon={TruckIcon}
        title="Suppliers"
        subtitle="What we owe, what we buy and how often (ACE Books)"
        actions={roles.includes("admin") ? <Button onClick={() => setAdding(true)}><PlusCircle className="mr-2 h-4 w-4" />Add supplier</Button> : undefined}
      />
      <KpiStrip
        items={[
          { label: "Active suppliers", value: t ? t.active : "—", icon: Users, sub: t ? `${t.suppliers} on file · bought from in the last 12 months` : undefined, onClick: () => setFilter("active") },
          { label: "We owe suppliers", value: t ? naira(t.balance) : "—", icon: Wallet, tone: (t?.overdue ?? 0) > 0 ? "warning" : "default",
            sub: t ? `${naira(t.overdue)} past due · ${t.with_balance} suppliers` : undefined, onClick: () => setFilter("balance") },
          { label: "Bought in the last 12 months", value: t ? naira(t.last12) : "—", icon: ShoppingCart, sub: data?.as_of ? `to ${fmtDate(data.as_of)}` : undefined },
          { label: "Suppliers in credit", value: t ? naira(t.credits) : "—", icon: Wallet, sub: "paid ahead / unapplied payments" },
        ]}
      />
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map(([k, label]) => (
          <Button key={k} size="sm" variant={filter === k ? "default" : "outline"} className="h-8" onClick={() => setFilter(k)}>{label}</Button>
        ))}
        <Input className="ml-auto h-8 w-64" placeholder="Search supplier" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
          ) : rows.length === 0 ? (
            <p className="p-8 text-center text-sm text-muted-foreground">No suppliers in this view.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Supplier</TableHead><TableHead className="text-right">Last 12 months</TableHead>
                  <TableHead className="text-right">All time</TableHead><TableHead className="text-right">Items</TableHead>
                  <TableHead className="text-right">Buys every</TableHead><TableHead className="text-right">Price trend</TableHead>
                  <TableHead>Last invoice</TableHead><TableHead className="text-right">We owe</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((s) => (
                  <TableRow key={s.id} className="cursor-pointer" onClick={() => setPicked(s)}>
                    <TableCell className="max-w-[260px]">
                      <div className="truncate font-medium">{s.name}</div>
                      <div className="truncate text-[11px] text-muted-foreground">{[s.payment_terms, s.phone, s.contact_email].filter(Boolean).join(" · ") || "no contact details"}</div>
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap">{s.last12 ? naira(s.last12) : "—"}</TableCell>
                    <TableCell className="text-right whitespace-nowrap">{s.lifetime ? naira(s.lifetime) : "—"}<div className="text-[11px] text-muted-foreground">{num(s.invoices)} invoices</div></TableCell>
                    <TableCell className="text-right">{s.items ? num(s.items) : "—"}</TableCell>
                    <TableCell className="text-right whitespace-nowrap">{s.avg_gap_days != null ? `${num(s.avg_gap_days)} days` : "—"}</TableCell>
                    <TableCell className="text-right whitespace-nowrap"><PriceTrend v={s.price_change_pct} /></TableCell>
                    <TableCell className="text-xs whitespace-nowrap">{s.last_purchase ? fmtDate(s.last_purchase) : "—"}</TableCell>
                    <TableCell className="text-right whitespace-nowrap">
                      {s.balance ? naira(s.balance) : "—"}
                      {s.overdue > 0 && <div className="text-[11px] text-amber-700 dark:text-amber-300">{naira(s.overdue)} past due</div>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">
        Buying history is the Sage purchase journal up to go-live plus supplier bills posted in ACE Books since. "Price trend" compares the average unit cost of the same items
        over the last 6 months with the 12 months before, weighted by spend.
      </p>

      <DetailSheet open={!!picked} onOpenChange={(o) => !o && setPicked(null)} title={picked?.name ?? ""} icon={TruckIcon}
                   description={picked ? [picked.code, picked.payment_terms].filter(Boolean).join(" · ") : undefined}>
        {picked && (
          <div className="space-y-4 text-sm">
            <Facts items={[
              ["Bought, last 12 months", naira(picked.last12)], ["Bought, all time", naira(picked.lifetime)], ["Invoices", num(picked.invoices)],
              ["Buying since", picked.first_purchase ? fmtDate(picked.first_purchase) : "—"], ["Last invoice", picked.last_purchase ? fmtDate(picked.last_purchase) : "—"],
              ["Buys every", picked.avg_gap_days != null ? `${num(picked.avg_gap_days)} days` : "—"],
              ["Items bought", num(picked.items)], ["Price trend", <PriceTrend v={picked.price_change_pct} />], ["Contact", picked.contact_name ?? "—"],
              ["Phone", picked.phone ?? "—"], ["Email", picked.contact_email ?? "—"], ["Address", picked.address ?? "—"],
            ]} />
            <div className="border-t pt-3">
              <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">Account (ACE Books)</div>
              <RecordView t={{ type: "supplier", id: picked.id }} />
            </div>
          </div>
        )}
      </DetailSheet>

      <DetailSheet open={adding} onOpenChange={setAdding} title="Add supplier" icon={PlusCircle}
                   description="The supplier's balance comes from the bills and payments recorded in ACE Books."
                   footer={<Button onClick={create} disabled={saving} className="w-full">{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Add supplier</Button>}>
        {([["name", "Name"], ["contact_name", "Contact person"], ["contact_email", "Email"], ["phone", "Phone"], ["address", "Address"],
           ["payment_terms", "Payment terms"], ["tax_id", "Tax ID"], ["bank_details", "Bank details"]] as [keyof typeof BLANK, string][]).map(([k, label]) => (
          <div key={k} className="space-y-1">
            <Label className="text-xs">{label}</Label>
            <Input value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
          </div>
        ))}
      </DetailSheet>
    </motion.div>
  );
}

function PriceTrend({ v }: { v: number | null | undefined }) {
  if (v == null) return <span className="text-muted-foreground">—</span>;
  const n = Number(v);
  const cls = n > 2 ? "text-red-600 dark:text-red-400" : n < -2 ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground";
  return <span className={cls}>{n > 0 ? "+" : ""}{n.toFixed(1)}%</span>;
}
