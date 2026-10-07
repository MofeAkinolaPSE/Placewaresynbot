/** "Write a report on this" - opens the report page with this record already chosen (step 3: review). */
import { Link } from "react-router-dom";
import { FileText } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ReportButton({ type, kind, id, label = "Report", size = "sm", variant = "outline", className = "" }: {
  type: string; kind: string; id: string | number; label?: string; size?: "sm" | "default" | "icon"; variant?: "outline" | "ghost" | "default"; className?: string;
}) {
  return (
    <Link to={`/reports/new?${new URLSearchParams({ type, kind, id: String(id) })}`} onClick={(e) => e.stopPropagation()}>
      <Button size={size} variant={variant} className={className} title="Write a report on this record">
        <FileText className="mr-1 h-3.5 w-3.5" />{label}
      </Button>
    </Link>
  );
}
