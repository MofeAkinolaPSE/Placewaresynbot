/** GL account picker for an item's accounts (Maintain -> Inventory Items, New item): the chart of accounts
 *  of the right kind - sales: revenue accounts; inventory: asset accounts; cost of sales: expense accounts -
 *  shown as "40510 · Prevenar 13", as Sage shows the account name beside the code. A drop-down with a search
 *  box (client, 28 Oct): type the account number or part of its name to find it instead of scrolling. */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Search, X } from "lucide-react";
import { books } from "@/lib/books-api";

export type GlKind = "sales" | "inventory" | "cogs" | "any";
const TYPE: Record<GlKind, string | undefined> = { sales: "REVENUE", inventory: "ASSET", cogs: "EXPENSE", any: undefined };

export function GlSelect({ kind, value, onChange, allowDefault = false, label }: {
  kind: GlKind; value: string; onChange: (code: string) => void; allowDefault?: boolean; label: string;
}) {
  const { data } = useQuery({ queryKey: ["books", "maintain-accounts", kind], staleTime: 5 * 60_000,
                              queryFn: () => books.get<{ code: string; name: string }[]>("/maintain/accounts", { account_type: TYPE[kind] }) });
  const list = data ?? [];
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [hi, setHi] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const current = list.find((a) => a.code === value);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return list;
    // account numbers that start with what was typed first, then any code or name containing it
    const starts = list.filter((a) => a.code.toLowerCase().startsWith(t));
    return [...starts, ...list.filter((a) => !starts.includes(a) && `${a.code} ${a.name}`.toLowerCase().includes(t))];
  }, [list, q]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  useEffect(() => { setHi(0); }, [q]);
  const pick = (code: string) => { onChange(code); setOpen(false); setQ(""); };
  const start = () => { setOpen(true); setQ(""); setTimeout(() => input.current?.focus(), 0); };
  return (
    <div ref={box} className="relative">
      <button type="button" aria-label={label} aria-haspopup="listbox" aria-expanded={open} onClick={() => (open ? setOpen(false) : start())}
              className="flex h-10 w-full items-center gap-2 rounded-md border bg-background px-3 text-left text-sm">
        <span className={`flex-1 truncate ${value ? "" : "text-muted-foreground"}`}>
          {value ? (current ? `${current.code} · ${current.name}` : value) : allowDefault ? "Default account" : "Choose an account…"}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 opacity-60" />
      </button>
      {open && (
        <div className="absolute z-50 mt-1 w-full min-w-[260px] rounded-md border bg-popover shadow-md">
          <div className="flex items-center gap-2 border-b px-2">
            <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
            <input ref={input} className="h-9 flex-1 bg-transparent text-sm outline-none" placeholder="Type the account number or name"
                   aria-label={`Search ${label}`} value={q} onChange={(e) => setQ(e.target.value)}
                   onKeyDown={(e) => {
                     if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(h + 1, shown.length - 1)); }
                     else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
                     else if (e.key === "Enter") { e.preventDefault(); if (shown[hi]) pick(shown[hi].code); }
                     else if (e.key === "Escape") setOpen(false);
                   }} />
            {q && <button type="button" aria-label="Clear search" onClick={() => setQ("")}><X className="h-4 w-4 text-muted-foreground" /></button>}
          </div>
          <div role="listbox" className="max-h-64 overflow-y-auto py-1">
            {!q && (
              <button type="button" className="block w-full px-3 py-1.5 text-left text-sm text-muted-foreground hover:bg-accent" onClick={() => pick("")}>
                {allowDefault ? "Default account" : "No account"}</button>)}
            {shown.length === 0 && <div className="px-3 py-2 text-xs text-muted-foreground">No account matches "{q}"</div>}
            {shown.map((a, i) => (
              <button key={a.code} type="button" role="option" aria-selected={a.code === value}
                      className={`block w-full px-3 py-1.5 text-left text-sm hover:bg-accent ${i === hi ? "bg-accent" : ""} ${a.code === value ? "font-semibold" : ""}`}
                      onMouseEnter={() => setHi(i)} onClick={() => pick(a.code)}>
                <span className="font-mono">{a.code}</span> · {a.name}
              </button>))}
          </div>
        </div>
      )}
    </div>
  );
}
