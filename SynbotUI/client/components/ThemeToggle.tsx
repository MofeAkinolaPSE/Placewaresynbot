import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Moon, Sun, Monitor } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

type ThemeToggleProps = {
  className?: string;
  /** Show the current mode's name next to the icon. */
  showLabel?: boolean;
  /** "icon" flips light <-> dark; "segmented" also exposes System. */
  variant?: "icon" | "segmented";
};

/**
 * Light/dark switch.
 *
 * next-themes resolves the active theme on the client, so the first render
 * has no reliable answer -- we hold a neutral placeholder until mount to
 * avoid a flash of the wrong icon.
 */
export function ThemeToggle({
  className,
  showLabel = false,
  variant = "icon",
}: ThemeToggleProps) {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  const isDark = mounted && resolvedTheme === "dark";

  if (variant === "segmented") {
    const options = [
      { value: "light", label: "Light", Icon: Sun },
      { value: "dark", label: "Dark", Icon: Moon },
      { value: "system", label: "System", Icon: Monitor },
    ] as const;

    return (
      <div
        role="radiogroup"
        aria-label="Colour theme"
        className={cn(
          "inline-flex items-center gap-0.5 rounded-xl border border-border/60 bg-muted/50 p-0.5",
          className,
        )}
      >
        {options.map(({ value, label, Icon }) => {
          const active = mounted && theme === value;
          return (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => setTheme(value)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-all duration-200",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-1 focus-visible:ring-offset-background",
                active
                  ? "bg-background text-primary shadow-elevation-1"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          );
        })}
      </div>
    );
  }

  const nextTheme = isDark ? "light" : "dark";
  const label = isDark ? "Switch to light mode" : "Switch to dark mode";

  const button = (
    <button
      type="button"
      onClick={() => setTheme(nextTheme)}
      aria-label={label}
      aria-pressed={isDark}
      title={label}
      className={cn(
        "group relative inline-flex h-8 items-center gap-2 rounded-lg border border-border/60 bg-muted/40 px-2 text-muted-foreground transition-all duration-200",
        "hover:border-primary/35 hover:bg-primary/10 hover:text-primary",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        showLabel ? "px-2.5" : "w-8 justify-center px-0",
        className,
      )}
    >
      {/* Both icons are always mounted and cross-fade, so the swap reads as
          one control changing state rather than two icons swapping out. */}
      <span className="relative block h-4 w-4 shrink-0">
        <Sun
          className={cn(
            "absolute inset-0 h-4 w-4 transition-all duration-300",
            isDark
              ? "rotate-0 scale-100 opacity-100"
              : "-rotate-90 scale-50 opacity-0",
          )}
        />
        <Moon
          className={cn(
            "absolute inset-0 h-4 w-4 transition-all duration-300",
            isDark
              ? "rotate-90 scale-50 opacity-0"
              : "rotate-0 scale-100 opacity-100",
          )}
        />
      </span>
      {showLabel && (
        <span className="text-xs font-medium">{isDark ? "Light" : "Dark"}</span>
      )}
    </button>
  );

  if (showLabel) return button;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{button}</TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  );
}

export default ThemeToggle;
