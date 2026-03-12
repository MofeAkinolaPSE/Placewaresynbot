import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface PagePlaceholderProps {
  title: string;
  description: string;
  icon: React.ReactNode;
}

const PagePlaceholder = ({
  title,
  description,
  icon,
}: PagePlaceholderProps) => {
  return (
    <div className="pw-page-surface flex min-h-screen items-center justify-center p-8">
      <div className="text-center max-w-md">
        <div className="flex justify-center mb-6 text-primary/50">
          {icon}
        </div>
        <h1 className="text-2xl font-bold text-foreground mb-3">{title}</h1>
        <p className="text-muted-foreground mb-6">{description}</p>
        <div className="rounded-xl border border-info/30 bg-info/15 p-4 text-left">
          <div className="flex gap-3">
            <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-info" />
            <div>
              <p className="font-medium text-info">Page in Development</p>
              <p className="mt-1 text-sm text-info">
                To add content to this page, continue prompting in the chat to
                develop the full page design.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default PagePlaceholder;
