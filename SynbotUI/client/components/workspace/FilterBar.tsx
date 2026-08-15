import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Radix Select can't have value="" — every existing filter in this app maps
// a sentinel back to "" in state (see QualityControl.tsx / Frontdesk.tsx).
// FilterBar owns that translation internally so callers only ever see a
// plain "" for "no filter selected".
const ALL_SENTINEL = "__all__";

export type FilterSelect = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder?: string;
  className?: string;
};

/** ACE Workspace Standard — Filter bar: search input + dropdown filters. */
export function FilterBar({
  search,
  selects,
}: {
  search?: { value: string; onChange: (value: string) => void; placeholder?: string };
  selects?: FilterSelect[];
}) {
  return (
    <div className="flex flex-col sm:flex-row gap-2">
      {search && (
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            className="pl-9"
            placeholder={search.placeholder ?? "Search..."}
            value={search.value}
            onChange={(e) => search.onChange(e.target.value)}
          />
        </div>
      )}
      {selects?.map((s) => (
        <Select
          key={s.label}
          value={s.value || ALL_SENTINEL}
          onValueChange={(v) => s.onChange(v === ALL_SENTINEL ? "" : v)}
        >
          <SelectTrigger className={s.className ?? "w-[170px]"}>
            <SelectValue placeholder={s.placeholder ?? s.label} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_SENTINEL}>{s.placeholder ?? `All ${s.label}`}</SelectItem>
            {s.options.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ))}
    </div>
  );
}
