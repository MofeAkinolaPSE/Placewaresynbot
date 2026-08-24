import type { LucideIcon } from "lucide-react";

/**
 * ACE Workspace Standard — Header region.
 * Standardizes the most common of this app's ~4 divergent page-header
 * variants (see backend/docs/ACE-Workspace-Standard.md Chapter 2).
 */
export function PageHeader({
  icon: Icon,
  title,
  subtitle,
  actions,
}: {
  icon: LucideIcon;
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div className="flex min-w-0 items-center gap-3">
        <div className="h-10 w-10 rounded-full bg-blue-100 flex items-center justify-center shrink-0 dark:bg-blue-500/15">
          <Icon className="h-5 w-5 text-blue-700 dark:text-blue-300" />
        </div>
        <div className="min-w-0">
          <h1 className="truncate text-xl font-bold tracking-tight sm:text-2xl">{title}</h1>
          {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
        </div>
      </div>
      {/* Action buttons wrap rather than push the header wider than the
          viewport -- several pages pass three or four of them. */}
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
