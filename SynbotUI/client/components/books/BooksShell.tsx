import { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { BookOpen, CalendarRange } from "lucide-react";
import { PageHeader } from "@/components/workspace/PageHeader";
import { fmtDate } from "@/lib/books-api";
import { useBooks } from "./kit";
import { DrillProvider } from "./lineage";

const NAV = [
  { to: "/finance/books", label: "Control Tower", end: true },
  { to: "/finance/books/sales", label: "Sales & Receivables" },
  { to: "/finance/books/purchases", label: "Purchases & Payables" },
  { to: "/finance/books/stock", label: "Stock" },
  { to: "/finance/books/banking", label: "Banking" },
  { to: "/finance/books/ledger", label: "Journals & Ledger" },
  { to: "/finance/books/statements", label: "Financial Statements" },
  { to: "/finance/books/reports", label: "Report Center" },
  { to: "/finance/books/assets", label: "Fixed Assets" },
  { to: "/finance/books/close", label: "Close & Controls" },
  { to: "/finance/books/setup", label: "Setup" },
];

/** Frame shared by every ACE Books screen: title, company, open period, section nav. */
export function BooksShell({ title, subtitle, actions, children }: { title: string; subtitle?: string; actions?: ReactNode; children: ReactNode }) {
  const { data: ctx } = useBooks<any>(["context"], "/context");
  const period = ctx?.period;
  return (
    <DrillProvider>
    <div className="space-y-5 p-4 md:p-8">
      <PageHeader icon={BookOpen} title={title}
                  subtitle={subtitle ?? (ctx?.entity ? `${ctx.entity.name} · ACE Books` : "ACE Books")}
                  actions={<>
                    {period && (
                      <span className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs">
                        <CalendarRange className="h-3.5 w-3.5" />
                        {period.name} · {period.status.toLowerCase()}
                      </span>
                    )}
                    {ctx?.settings?.cutover_date && (
                      <span className="inline-flex items-center rounded-full border px-3 py-1 text-xs text-muted-foreground">
                        Live since {fmtDate(ctx.settings.cutover_date)}
                      </span>
                    )}
                    {actions}
                  </>} />
      <nav className="-mx-1 flex gap-1 overflow-x-auto border-b pb-px">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end}
                   className={({ isActive }) => `whitespace-nowrap rounded-t-md px-3 py-2 text-sm ${isActive ? "border-b-2 border-primary font-semibold text-foreground" : "text-muted-foreground hover:text-foreground"}`}>
            {n.label}
          </NavLink>
        ))}
      </nav>
      {children}
    </div>
    </DrillProvider>
  );
}
