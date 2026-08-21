import { FileText } from "lucide-react";
import { PageHeader } from "@/components/workspace/PageHeader";
import { InvoicesTab } from "@/components/frontdesk/InvoicesTab";

/**
 * Broadly-accessible invoice list/detail view — every authenticated team
 * member can view invoices here (read-only unless their role also grants
 * QC/Finance/Dispatch action permissions, enforced by InvoiceActionPanel and
 * the backend). The full Frontdesk department workspace (Queue, New Walk-in,
 * Reports tabs) stays restricted to Frontdesk-department roles as before —
 * this page only surfaces the Invoices tab, standalone, for everyone else.
 */
export default function AllInvoices() {
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        icon={FileText}
        title="All Invoices"
        subtitle="View invoice status and history across every department. QC, Finance, and Dispatch actions still require the relevant role."
      />
      <InvoicesTab />
    </div>
  );
}
