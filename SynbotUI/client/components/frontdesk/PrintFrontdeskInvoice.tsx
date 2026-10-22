/**
 * Print a Frontdesk invoice from wherever it is shown or raised (finance meeting 4: "as soon as you
 * raise an invoice you can print it, on whatever page you raised it"). Loads the full invoice with its
 * walk-in (customer details, batch numbers filled from Stock -> Batch numbers & dates) and prints the
 * same paper invoice as Frontdesk -> All invoices.
 */
import { useState } from "react";
import { Loader2, Printer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api-client";
import { printInvoice } from "./InvoicesTab";

export function PrintFrontdeskInvoiceButton({ invoiceId, size = "sm", className = "", label = "Print invoice" }: {
  invoiceId: string; size?: "sm" | "default"; className?: string; label?: string;
}) {
  const [busy, setBusy] = useState(false);
  const run = async () => {
    // open the window now, while the click still counts, so the browser does not block it
    const win = window.open("", "_blank", "width=1000,height=800");
    setBusy(true);
    try {
      const d = await api.frontdesk.getInvoice(invoiceId);
      if (d?.invoice) printInvoice(d.invoice, d.walk_in, win);
      else win?.close();
    } catch {
      win?.close();
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button size={size} variant="outline" className={`gap-1.5 ${className}`} disabled={busy} onClick={run}>
      {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Printer className="h-4 w-4" />}{label}
    </Button>
  );
}
