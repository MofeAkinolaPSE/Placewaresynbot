import React, { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api-client";

type Product = { id?: number; sku?: string; name: string };

export default function InventoryAutoComplete({ onSelect }: { onSelect: (p: Product) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!q || q.length < 2) {
      setResults([]);
      return;
    }
    let mounted = true;
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const res = await api.inventory.search(q);
        if (mounted) setResults(Array.isArray(res) ? res : []);
      } catch (_e) {
        if (mounted) setResults([]);
      } finally {
        if (mounted) setLoading(false);
      }
    }, 300);

    return () => {
      mounted = false;
      clearTimeout(t);
    };
  }, [q]);

  return (
    <div className="relative">
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search inventory..." />
      {loading && <div className="text-xs text-muted-foreground mt-1">Searching...</div>}
      {results.length > 0 && (
        <ul className="absolute z-40 mt-1 w-full bg-card border rounded shadow max-h-48 overflow-auto">
          {results.map((r, idx) => (
            <li
              key={r.id ?? r.sku ?? idx}
              className="p-2 hover:bg-accent/10 cursor-pointer"
              onClick={() => {
                onSelect(r);
                setQ("");
                setResults([]);
              }}
            >
              <div className="text-sm font-medium">{r.name}</div>
              {r.sku && <div className="text-xs text-muted-foreground">{r.sku}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
