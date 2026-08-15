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
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-full bg-blue-100 flex items-center justify-center shrink-0">
          <Icon className="h-5 w-5 text-blue-700" />
        </div>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}
