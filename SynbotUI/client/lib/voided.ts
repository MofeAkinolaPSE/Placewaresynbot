/**
 * Voided records in lists and exports - one rule for the whole app.
 *
 *  - A voided invoice, receipt, bill, payment or voucher (status VOID / VOIDED, a Frontdesk invoice
 *    "cancelled"), a journal posted and reversed the same day, or the credit note that voided a Sage
 *    invoice: the server marks these `voided: true` or by status.
 *  - Lists keep showing them until someone presses "Clear voided"; the choice is remembered per list
 *    on this computer, and "Show voided" brings them back. Nothing is deleted - they stay in their
 *    record's history and the audit trail.
 *  - CSV exports never contain them (lib/books-api downloadCsv and the CsvButton table export), so a
 *    file handed to the auditors matches what stands in the books. Ledgers already leave out an entry
 *    voided the same day it was posted (src/fin/ledger.py same_day_void), so their totals still agree.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

const VOID_STATUSES = new Set(["void", "voided", "cancelled", "canceled"]);

export function isVoidStatus(status: unknown): boolean {
  return VOID_STATUSES.has(String(status ?? "").trim().toLowerCase());
}

/** A row the server marked (`voided`) wins; otherwise its status says. A journal "reversed" on a later
 *  date is not voided here - it changed the books in between and stays in lists and exports. */
export function isVoided(row: Record<string, any> | null | undefined): boolean {
  if (!row) return false;
  if (typeof row.voided === "boolean") return row.voided;
  return isVoidStatus(row.status) || isVoidStatus(row.Status);
}

export function withoutVoided<T extends Record<string, any>>(rows: T[] | undefined | null): T[] {
  return (rows ?? []).filter((r) => !isVoided(r));
}

const storeKey = (list: string) => `ace.clearVoided.${list}`;
const read = (list: string, fallback: boolean) => { try { const v = localStorage.getItem(storeKey(list)); return v === null ? fallback : v === "1"; } catch { return fallback; } };
const write = (list: string, v: boolean) => { try { localStorage.setItem(storeKey(list), v ? "1" : "0"); } catch { /* private window */ } };

/** `rows` with the voided ones taken out once the list is cleared, plus what the Clear button needs.
 *  `clearedByDefault`: a working list that starts without them, until someone asks to see them. */
export function useClearVoided<T extends Record<string, any>>(list: string, rows: T[] | undefined | null, clearedByDefault = false) {
  const [cleared, setCleared] = useState(() => read(list, clearedByDefault));
  useEffect(() => setCleared(read(list, clearedByDefault)), [list, clearedByDefault]);
  const toggle = useCallback(() => setCleared((c) => { write(list, !c); return !c; }), [list]);
  const voidedCount = useMemo(() => (rows ?? []).filter(isVoided).length, [rows]);
  const visible = useMemo(() => (cleared ? withoutVoided(rows) : rows ?? []), [rows, cleared]);
  return { rows: visible, cleared, voidedCount, toggle };
}
