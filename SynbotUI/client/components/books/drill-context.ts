/**
 * Financial lineage: any figure in ACE Books can open the record behind it
 * (report -> account -> ledger line -> journal -> source document -> party /
 * product / batch) in a sheet on top of the current page, without navigating
 * away. Pages get it for free via BooksShell's <DrillProvider>.
 */
import { createContext, useContext } from "react";

export type DrillType =
  | "journal" | "account" | "invoice" | "receipt" | "creditnote" | "bill" | "payment" | "debitnote"
  | "voucher" | "customer" | "supplier" | "product" | "batch" | "adjustment" | "loan" | "asset" | "sageinvoice" | "sagebill"
  /** id "<date>|<reference>|<customer name>" */
  | "sagereceipt"
  /** id "<date>|<jrnl>|<reference>" - every line of one Sage General Ledger transaction */
  | "sagetxn";

/** The record behind a Sage General Ledger line: the invoice for a sale, else the whole transaction. */
export function sageLineTarget(l: { date: string; jrnl?: string | null; reference?: string | null }): DrillTarget {
  const ref = l.reference ?? "";
  if ((l.jrnl === "SJ" || l.jrnl === "COGS") && /^\d{3,}$/.test(ref)) return { type: "sageinvoice", id: ref, label: ref };
  return { type: "sagetxn", id: `${l.date}|${l.jrnl ?? ""}|${ref}`, label: ref || l.jrnl || "" };
}

export type DrillTarget = { type: DrillType; id: string; label?: string };

export const DrillContext = createContext<{ open: (t: DrillTarget) => void } | null>(null);

export function useDrill() {
  return useContext(DrillContext);
}

/** Map a posting source (journal or stock movement) to the document it came from. */
export const SOURCE_TYPES: Record<string, DrillType> = {
  SALES_INVOICE: "invoice",
  CUSTOMER_RECEIPT: "receipt",
  CREDIT_NOTE: "creditnote",
  SUPPLIER_BILL: "bill",
  SUPPLIER_PAYMENT: "payment",
  DEBIT_NOTE: "debitnote",
  CASH_VOUCHER: "voucher",
  STOCK_ADJUSTMENT: "adjustment",
  STOCK_LOAN: "loan",
  FIXED_ASSET: "asset",
  FIXED_ASSET_DISPOSAL: "asset",
};

export function sourceTarget(sourceType?: string | null, sourceId?: string | null): DrillTarget | null {
  if (!sourceType || !sourceId) return null;
  const t = SOURCE_TYPES[sourceType];
  // Stock-loan movements reference the loan number, not its id - the loan sheet resolves both.
  return t ? { type: t, id: String(sourceId) } : null;
}
