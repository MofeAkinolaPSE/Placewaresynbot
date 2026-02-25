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
    <div className="p-8 h-screen flex items-center justify-center">
      <div className="text-center max-w-md">
        <div className="flex justify-center mb-6 text-primary/50">
          {icon}
        </div>
        <h1 className="text-2xl font-bold text-foreground mb-3">{title}</h1>
        <p className="text-muted-foreground mb-6">{description}</p>
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-left">
          <div className="flex gap-3">
            <AlertCircle className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-medium text-blue-900">Page in Development</p>
              <p className="text-sm text-blue-700 mt-1">
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
