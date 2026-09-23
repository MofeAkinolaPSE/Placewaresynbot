import { useEffect, useMemo, useState } from "react";
import { Loader2, X, Search, Users } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api-client";

export type RecipientKind = "customer" | "supplier";

export interface Recipient {
  kind: RecipientKind;
  id: string | number;
  name: string;
  phone?: string | null;
  email?: string | null;
}

const keyOf = (r: Recipient) => `${r.kind}:${r.id}`;

/**
 * Multi-select recipient picker for bulk SMS/email.
 *
 * Customers are searched server-side (/crm/customers/search, min 2 chars);
 * suppliers have no search endpoint, so the full list is fetched once and
 * filtered client-side. Contacts that can't receive on the active channel are
 * still selectable but flagged, because "why did this person not get it?" is
 * otherwise invisible until after the send.
 */
export function RecipientPicker({
  value,
  onChange,
  channel,
}: {
  value: Recipient[];
  onChange: (next: Recipient[]) => void;
  channel: "sms" | "email";
}) {
  const [kind, setKind] = useState<RecipientKind>("customer");
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Recipient[]>([]);
  const [loading, setLoading] = useState(false);
  const [suppliers, setSuppliers] = useState<Recipient[] | null>(null);

  // Suppliers: fetch once on first switch, then filter locally.
  useEffect(() => {
    if (kind !== "supplier" || suppliers !== null) return;
    let mounted = true;
    setLoading(true);
    api.suppliers
      .list()
      .then((rows: any) => {
        const list = Array.isArray(rows) ? rows : rows?.data ?? [];
        if (mounted)
          setSuppliers(
            list.map((s: any) => ({
              kind: "supplier" as const,
              id: s.id,
              name: s.name,
              phone: s.phone,
              email: s.contact_email,
            })),
          );
      })
      .catch(() => mounted && setSuppliers([]))
      .finally(() => mounted && setLoading(false));
    return () => {
      mounted = false;
    };
  }, [kind, suppliers]);

  useEffect(() => {
    if (kind === "supplier") {
      const all = suppliers ?? [];
      const needle = q.trim().toLowerCase();
      setResults(
        (needle ? all.filter((s) => s.name?.toLowerCase().includes(needle)) : all).slice(0, 25),
      );
      return;
    }

    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    let mounted = true;
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const res: any = await api.crm.searchCustomers(q.trim(), 20);
        const rows = res?.data ?? res ?? [];
        if (mounted)
          setResults(
            (Array.isArray(rows) ? rows : []).map((c: any) => ({
              kind: "customer" as const,
              id: c.id,
              name: c.name,
              phone: c.phone,
              email: c.email,
            })),
          );
      } catch {
        if (mounted) setResults([]);
      } finally {
        if (mounted) setLoading(false);
      }
    }, 300);
    return () => {
      mounted = false;
      clearTimeout(t);
    };
  }, [q, kind, suppliers]);

  const selectedKeys = useMemo(() => new Set(value.map(keyOf)), [value]);

  const toggle = (r: Recipient) => {
    if (selectedKeys.has(keyOf(r))) {
      onChange(value.filter((v) => keyOf(v) !== keyOf(r)));
    } else {
      onChange([...value, r]);
    }
  };

  const canReceive = (r: Recipient) =>
    channel === "sms" ? Boolean(r.phone) : Boolean(r.email && String(r.email).includes("@"));

  const reachable = value.filter(canReceive).length;
  const unreachable = value.length - reachable;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium">Recipients</label>
        {value.length > 0 && (
          <span className="text-xs text-muted-foreground">
            {reachable} reachable
            {unreachable > 0 && ` · ${unreachable} missing ${channel === "sms" ? "phone" : "email"}`}
          </span>
        )}
      </div>

      <div className="flex gap-1">
        {(["customer", "supplier"] as RecipientKind[]).map((k) => (
          <Button
            key={k}
            type="button"
            size="sm"
            variant={kind === k ? "default" : "outline"}
            className="h-7 text-xs capitalize"
            onClick={() => {
              setKind(k);
              setQ("");
            }}
          >
            {k}s
          </Button>
        ))}
      </div>

      <div className="relative">
        <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          className="pl-7"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={kind === "customer" ? "Search customers (min 2 chars)..." : "Filter suppliers..."}
        />
        {loading && (
          <Loader2 className="absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 animate-spin text-muted-foreground" />
        )}
      </div>

      {results.length > 0 && (
        <ul className="max-h-44 overflow-auto rounded border bg-card">
          {results.map((r) => {
            const selected = selectedKeys.has(keyOf(r));
            const ok = canReceive(r);
            return (
              <li
                key={keyOf(r)}
                onClick={() => toggle(r)}
                className={`flex cursor-pointer items-center justify-between gap-2 p-2 hover:bg-accent/10 ${
                  selected ? "bg-accent/10" : ""
                }`}
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{r.name}</div>
                  <div className="truncate text-xs text-muted-foreground">
                    {channel === "sms" ? r.phone || "no phone on file" : r.email || "no email on file"}
                  </div>
                </div>
                {!ok && (
                  <Badge variant="outline" className="shrink-0 text-[10px]">
                    unreachable
                  </Badge>
                )}
                {selected && <span className="shrink-0 text-xs text-primary">selected</span>}
              </li>
            );
          })}
        </ul>
      )}

      {value.length === 0 ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Users className="h-3.5 w-3.5" />
          No recipients selected — nothing will be sent.
        </p>
      ) : (
        <div className="flex flex-wrap gap-1">
          {value.map((r) => (
            <Badge
              key={keyOf(r)}
              variant={canReceive(r) ? "secondary" : "outline"}
              className="gap-1 pr-1"
            >
              <span className="max-w-[140px] truncate">{r.name}</span>
              <button
                type="button"
                onClick={() => toggle(r)}
                className="rounded-full p-0.5 hover:bg-background/60"
                aria-label={`Remove ${r.name}`}
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
