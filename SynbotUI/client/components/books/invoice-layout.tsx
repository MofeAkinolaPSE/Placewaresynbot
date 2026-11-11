/**
 * ACE Books -> Setup -> Invoice layout: what every printed invoice of THIS branch shows - company name, address,
 * phones, email, website, bank details, payment note, footer and the default ship method - with a live preview.
 * Each branch (Lagos / Abuja) has its own; switch branch in the top bar to edit the other. Also where the branch's
 * next invoice number is set before its Sage history is loaded.
 */
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { act, ErrorNote, Loading, Section, useBooks } from "@/components/books/kit";
import { useMyBranches } from "@/components/BranchSwitcher";
import { books, BooksError, Dict } from "@/lib/books-api";
import { askConfirm, askText } from "@/lib/ask";

type Layout = {
  company_name: string;
  address_lines: string[];
  phones: string[];
  email: string;
  website: string;
  footer_left: string;
  payment_note: string;
  bank_lines: string[];
  default_shipping_method: string;
};

const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

export function InvoiceLayoutEditor() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useBooks<Dict>(["invoice-layout"], "/settings/invoice-layout");
  const { data: mine } = useMyBranches();
  const branch = mine?.current;
  const [f, setF] = useState<Record<string, string> | null>(null);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!data?.layout) return;
    const L = data.layout as Layout;
    setF({
      company_name: L.company_name ?? "", email: L.email ?? "", website: L.website ?? "", footer_left: L.footer_left ?? "",
      payment_note: L.payment_note ?? "", default_shipping_method: L.default_shipping_method ?? "",
      address_lines: (L.address_lines ?? []).join("\n"), phones: (L.phones ?? []).join("\n"), bank_lines: (L.bank_lines ?? []).join("\n"),
    });
  }, [data]);

  const body = (): Layout | null => f && ({
    company_name: f.company_name.trim(), email: f.email.trim(), website: f.website.trim(), footer_left: f.footer_left.trim(),
    payment_note: f.payment_note.trim(), default_shipping_method: f.default_shipping_method.trim(),
    address_lines: lines(f.address_lines), phones: lines(f.phones), bank_lines: lines(f.bank_lines),
  } as Layout);

  const refresh = () => qc.invalidateQueries({ queryKey: ["books"] });
  const save = async () => {
    const b = body();
    if (!b) return;
    if (!b.company_name) { setMsg("Give the company name"); return; }
    if (await act(() => books.put("/settings/invoice-layout", b), `Invoice layout saved${branch ? ` for ${branch.branch_name}` : ""}`)) { setMsg(""); refresh(); }
  };
  const reset = async () => {
    if (!(await askConfirm("Go back to ACE's built-in invoice details (the Lagos head office details)?"))) return;
    if (await act(() => books.put("/settings/invoice-layout", {}), "Invoice layout reset")) refresh();
  };
  const setNumber = async () => {
    const v = await askText("Next invoice number for this branch - the number after its last Sage invoice (e.g. 20451).", "");
    if (v === null || !v.trim()) return;
    try {
      const r = await books.put<{ next_invoice_number: string }>("/settings/invoice-numbering", { next: v.trim() });
      setMsg(`Next invoice: ${r.next_invoice_number}`);
      refresh();
    } catch (e) {
      setMsg(e instanceof BooksError ? e.message : "Could not set the invoice number");
    }
  };

  const canEdit = !!data?.can_edit;
  const preview = body();
  const field = (k: string, label: string, hint?: string, area = false) => (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      {area
        ? <Textarea rows={3} value={f?.[k] ?? ""} disabled={!canEdit} onChange={(e) => setF({ ...f!, [k]: e.target.value })} />
        : <Input value={f?.[k] ?? ""} disabled={!canEdit} onChange={(e) => setF({ ...f!, [k]: e.target.value })} />}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );

  return (
    <Section title={`Invoice layout${branch ? ` - ${branch.branch_name}` : ""}`}
             actions={canEdit ? <>
               <Button size="sm" variant="ghost" onClick={reset} disabled={!data?.customised}>Reset to default</Button>
               <Button size="sm" onClick={save} disabled={!f}>Save layout</Button>
             </> : undefined}>
      {isLoading && <Loading />}<ErrorNote error={error} />
      {data && !data.customised && branch && !branch.is_primary && (
        <div className="mb-4 flex items-start gap-2 rounded-md border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-sm text-amber-900 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{branch.branch_name}'s invoices still print the Lagos head office details. Enter {branch.branch_name}'s address, phones and bank account below and save.</span>
        </div>
      )}
      {!canEdit && data && <p className="mb-3 text-xs text-muted-foreground">Only Finance, management and admin can change the invoice layout.</p>}
      {f && (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="space-y-4">
            <p className="text-xs text-muted-foreground">
              Every invoice this branch prints uses these details (ACE Books, Frontdesk, Customer Workspace).
              {mine?.can_switch ? " To edit the other branch's, switch branch in the top bar." : ""}
            </p>
            {field("company_name", "Company name")}
            {field("address_lines", "Address", "One line per row", true)}
            <div className="grid gap-4 sm:grid-cols-2">
              {field("phones", "Phone numbers", "One per row", true)}
              <div className="space-y-4">{field("email", "Email")}{field("website", "Website")}</div>
            </div>
            {field("payment_note", "Payment note", "Printed above the bank details")}
            {field("bank_lines", "Bank details", "One line per row - account name, bank and number, any payment rule", true)}
            {field("footer_left", "Footer note", "e.g. goods received in good condition...", true)}
            {field("default_shipping_method", "Default ship via", "Used when an invoice does not choose one")}
            <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
              Invoice numbers: next <strong className="font-mono">{data?.next_invoice_number ?? "-"}</strong>
              {data?.last_invoice?.number && <span className="text-muted-foreground"> · last {data.last_invoice.number}</span>}
              {canEdit && data?.next_invoice_number === "Not set yet" && (
                <Button size="sm" variant="outline" className="ml-2 h-6 px-2 text-xs" onClick={setNumber}>Set</Button>
              )}
              {msg && <span className="ml-2 text-xs text-muted-foreground">{msg}</span>}
            </div>
          </div>
          {preview && (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Preview</p>
              <div className="rounded-md border bg-white p-5 text-[12px] leading-snug text-black shadow-sm" data-testid="layout-preview">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-base font-bold">{preview.company_name || "Company name"}</div>
                    {preview.address_lines.map((l, i) => <div key={i}>{l}</div>)}
                    {preview.phones.length > 0 && <div>Tel: {preview.phones.join(", ")}</div>}
                    {(preview.email || preview.website) && <div>{[preview.email, preview.website].filter(Boolean).join(" · ")}</div>}
                  </div>
                  <div className="text-right">
                    <div className="text-lg font-bold tracking-wide">INVOICE</div>
                    <div>Invoice No: {data?.next_invoice_number}</div>
                  </div>
                </div>
                <div className="my-4 grid grid-cols-4 border border-black text-[11px] font-semibold">
                  {["Qty", "Description", "Unit price", "Amount"].map((h) => <div key={h} className="border-r border-black px-2 py-1 last:border-r-0">{h}</div>)}
                </div>
                <div className="grid grid-cols-2 gap-4 text-[11px]">
                  <div className="whitespace-pre-line">{preview.footer_left}</div>
                  <div>
                    {preview.payment_note && <div className="font-semibold">{preview.payment_note}</div>}
                    {preview.bank_lines.map((l, i) => <div key={i}>{l}</div>)}
                  </div>
                </div>
                <div className="mt-3 text-[11px] text-neutral-600">Ship via: {preview.default_shipping_method || "-"}</div>
              </div>
            </div>
          )}
        </div>
      )}
    </Section>
  );
}
