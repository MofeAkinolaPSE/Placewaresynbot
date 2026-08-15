import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";

/**
 * ACE Workspace Standard — searchable typeahead for governed catalogues
 * (customers, items, GL accounts). Generalizes the existing hand-rolled
 * InventoryAutoComplete.tsx pattern (300ms debounce, min-2-chars,
 * absolutely-positioned results list) via generic fetch/key/label props
 * instead of hardcoding to one entity type. Deliberately not a cmdk/Popover
 * Combobox — no such dependency exists in this app yet and one feature
 * doesn't justify adding two.
 */
export function EntityAutocomplete<T>({
  fetchFn,
  getKey,
  getLabel,
  getSubtitle,
  onSelect,
  placeholder = "Search...",
  minChars = 2,
  debounceMs = 300,
}: {
  fetchFn: (query: string) => Promise<T[]>;
  getKey: (item: T) => string | number;
  getLabel: (item: T) => string;
  getSubtitle?: (item: T) => string | undefined;
  onSelect: (item: T) => void;
  placeholder?: string;
  minChars?: number;
  debounceMs?: number;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<T[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!q || q.length < minChars) {
      setResults([]);
      return;
    }
    let mounted = true;
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const res = await fetchFn(q);
        if (mounted) setResults(Array.isArray(res) ? res : []);
      } catch {
        if (mounted) setResults([]);
      } finally {
        if (mounted) setLoading(false);
      }
    }, debounceMs);

    return () => {
      mounted = false;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  return (
    <div className="relative">
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder} />
      {loading && (
        <div className="absolute right-3 top-1/2 -translate-y-1/2">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
        </div>
      )}
      {results.length > 0 && (
        <ul className="absolute z-40 mt-1 w-full bg-card border rounded shadow max-h-56 overflow-auto">
          {results.map((item) => (
            <li
              key={getKey(item)}
              className="p-2 hover:bg-accent/10 cursor-pointer"
              onClick={() => {
                onSelect(item);
                setQ("");
                setResults([]);
              }}
            >
              <div className="text-sm font-medium">{getLabel(item)}</div>
              {getSubtitle?.(item) && (
                <div className="text-xs text-muted-foreground">{getSubtitle(item)}</div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
