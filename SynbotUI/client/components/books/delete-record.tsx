/**
 * Delete a record made by mistake - an item or lot, a batch, a vendor, a customer, a GL account.
 *
 * The server decides (src/fin/deletion.py): a record can go only while nothing has been recorded against
 * it. The button asks first, then either confirms ("cannot be undone") or says what still uses the
 * record and what to do instead - e.g. make it inactive, which keeps its history in the books.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { act } from "@/components/books/kit";
import { books, Dict } from "@/lib/books-api";

export type RecordKind = "item" | "batch" | "vendor" | "customer" | "account";
const NOUN: Record<RecordKind, string> = { item: "item", batch: "batch", vendor: "vendor", customer: "customer", account: "account" };
const path = (kind: RecordKind, key: string) => `/records/${kind}?key=${encodeURIComponent(key)}`;

export function DeleteRecord({ kind, recordKey, name, label, onDeleted, onMakeInactive, size = "sm", iconOnly = false }: {
  kind: RecordKind;
  recordKey: string;
  /** what the record is called on screen, e.g. "CLEXANE 40mg(K)" */
  name: string;
  label?: string;
  onDeleted: () => void;
  /** offered when the record has history and can be made inactive instead */
  onMakeInactive?: () => void;
  size?: "sm" | "icon";
  iconOnly?: boolean;
}) {
  const qc = useQueryClient();
  const [check, setCheck] = useState<Dict | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const open = async () => {
    setBusy(true);
    const r = await act(() => books.get<Dict>(`/records/${kind}/can-delete`, { key: recordKey }));
    setBusy(false);
    if (r) { setReason(""); setCheck(r); }
  };
  const remove = async () => {
    setBusy(true);
    const r = await act(() => books.del<Dict>(path(kind, recordKey) + (reason.trim() ? `&reason=${encodeURIComponent(reason.trim())}` : "")),
      `${name} deleted`);
    setBusy(false);
    if (r) { setCheck(null); qc.invalidateQueries({ queryKey: ["books"] }); onDeleted(); }
  };
  const text = label ?? `Delete ${NOUN[kind]}`;
  return (
    <>
      <Button type="button" size={iconOnly ? "icon" : size === "icon" ? "icon" : "sm"} variant="outline" disabled={busy}
              className="text-red-600 hover:bg-red-50 hover:text-red-700 dark:hover:bg-red-500/10" onClick={open}
              aria-label={`${text}: ${name}`} title={text}>
        <Trash2 className={iconOnly ? "h-4 w-4" : "mr-1 h-4 w-4"} />{!iconOnly && text}
      </Button>
      <Dialog open={!!check} onOpenChange={(o) => { if (!o) setCheck(null); }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{check?.can_delete && check?.allowed ? `Delete ${name}?` : `${name} cannot be deleted`}</DialogTitle>
            <DialogDescription>
              {!check?.allowed ? "Your login cannot delete this kind of record - ask Finance or an administrator."
                : check?.can_delete ? "Nothing has been recorded against it. Deleting removes it for good - this cannot be undone (the audit trail keeps a copy)."
                : (check?.used_by ?? []).length ? "It is already used on:" : check?.message}
            </DialogDescription>
          </DialogHeader>
          {check?.allowed && !check?.can_delete && (check?.used_by ?? []).length > 0 && (
            <ul className="space-y-1 rounded-md border bg-muted/40 p-3 text-sm">
              {(check.used_by as Dict[]).map((u) => (
                <li key={u.what} className="flex justify-between gap-3"><span>{u.what}</span><span className="tabular-nums text-muted-foreground">{u.count >= 1000 ? "1000+" : u.count}</span></li>
              ))}
            </ul>
          )}
          {check?.allowed && !check?.can_delete && check?.instead && <p className="text-sm">{check.instead}</p>}
          {check?.allowed && check?.can_delete && (
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground" htmlFor="delete-reason">Reason (kept in the audit trail)</label>
              <Input id="delete-reason" placeholder="e.g. created by mistake / duplicate" value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
          )}
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setCheck(null)}>{check?.can_delete && check?.allowed ? "Cancel" : "Close"}</Button>
            {check?.allowed && !check?.can_delete && onMakeInactive && kind !== "batch" && kind !== "customer" && (
              <Button variant="secondary" onClick={() => { setCheck(null); onMakeInactive(); }}>Make it inactive</Button>
            )}
            {check?.allowed && check?.can_delete && (
              <Button className="bg-red-600 text-white hover:bg-red-700" disabled={busy} onClick={remove}>
                <Trash2 className="mr-1 h-4 w-4" />{busy ? "Deleting…" : `Delete ${NOUN[kind]}`}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
