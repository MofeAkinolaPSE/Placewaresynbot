import type { LucideIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

type Tone = "default" | "success" | "warning" | "danger";

// Reuses this app's existing badge palette (QualityControl.tsx /
// DataIntelligence.tsx) — no new colors introduced.
const TONE_CLASSES: Record<Tone, string> = {
  default: "text-foreground",
  success: "text-green-700 dark:text-green-300",
  warning: "text-amber-700 dark:text-amber-300",
  danger: "text-red-700 dark:text-red-300",
};

export type KpiItem = {
  label: string;
  value: string | number;
  icon?: LucideIcon;
  tone?: Tone;
  /** one short line under the value (basis, period, count) */
  sub?: string;
  onClick?: () => void;
};

/** ACE Workspace Standard — KPI strip, sits directly under the Header. */
export function KpiStrip({ items }: { items: KpiItem[] }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {items.map((item) => (
        <Card key={item.label} onClick={item.onClick}
              className={item.onClick ? "cursor-pointer transition-colors hover:border-primary/50" : undefined}>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">{item.label}</span>
              {item.icon && <item.icon className="h-4 w-4 text-muted-foreground" />}
            </div>
            <div className={`text-xl font-bold mt-1 ${TONE_CLASSES[item.tone ?? "default"]}`}>
              {item.value}
            </div>
            {item.sub && <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{item.sub}</div>}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
