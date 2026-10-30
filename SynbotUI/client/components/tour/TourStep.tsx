import { Check } from "lucide-react";
import type { TourStep } from "@/lib/tour-config";

/** One step of the welcome tour: what this part of the day is, where it lives in the menu, and what to press. */
export function TourStepContent({ step, index, total }: { step: TourStep; index: number; total: number }) {
  const Icon = step.icon;
  return (
    <div key={`${index}-${step.href}`} className="space-y-3 duration-200 animate-in fade-in slide-in-from-right-2">
      <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${((index + 1) / total) * 100}%` }} />
      </div>
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Icon className="h-4 w-4" /></div>
        <div className="min-w-0 space-y-0.5">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Step {index + 1} of {total}{step.page ? ` · ${step.page}` : ""}</p>
          <p className="text-base font-semibold leading-snug">{step.label}</p>
        </div>
      </div>
      <p className="text-sm leading-relaxed text-foreground/80">{step.description}</p>
      {step.points && step.points.length > 0 && (
        <ul className="space-y-1.5 rounded-md bg-muted/50 p-3">
          {step.points.map((pt, i) => (
            <li key={i} className="flex gap-2 text-sm leading-snug"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" /><span>{pt}</span></li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted-foreground">Want the details? Press <strong>Show me how</strong> at the top of this page for a step-by-step guide to every tab and button on it.</p>
    </div>
  );
}
