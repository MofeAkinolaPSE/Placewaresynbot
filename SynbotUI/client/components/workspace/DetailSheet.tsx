import type { LucideIcon } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

/**
 * ACE Workspace Standard — the one side-panel primitive (Modal/Panel
 * Priority: inline > side panel > modal dialog > new page). Standardizes
 * the width/scroll convention already used correctly once in this app
 * (SalesCRM.tsx's "Pre-call Intelligence Brief").
 */
export function DetailSheet({
  open,
  onOpenChange,
  title,
  description,
  icon: Icon,
  footer,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  icon?: LucideIcon;
  footer?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-xl overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            {Icon && <Icon className="h-5 w-5 text-primary" />}
            {title}
          </SheetTitle>
          {description && <SheetDescription>{description}</SheetDescription>}
        </SheetHeader>
        <div className="mt-4 space-y-4">{children}</div>
        {footer && <SheetFooter className="mt-6">{footer}</SheetFooter>}
      </SheetContent>
    </Sheet>
  );
}
