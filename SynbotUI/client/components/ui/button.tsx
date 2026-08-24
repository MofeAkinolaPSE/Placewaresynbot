import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "pw-tap inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium ring-offset-background transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        // Gradient (brand blue -> teal -> green) so the full palette shows on
        // every default button app-wide, not just hand-picked CTAs.
        default:
          "bg-gradient-primary text-primary-foreground shadow-elevation-1 hover:shadow-elevation-2 hover:brightness-110 active:translate-y-px active:shadow-elevation-1",
        destructive:
          "bg-destructive text-destructive-foreground shadow-elevation-1 hover:bg-destructive/90",
        outline:
          "border border-border bg-background text-foreground hover:border-primary/40 hover:bg-primary/5 hover:text-primary",
        secondary:
          "bg-secondary text-secondary-foreground shadow-elevation-1 hover:bg-secondary/85",
        // Deep-teal accent is a dark fill -- pair it with light text.
        accent:
          "bg-accent text-accent-foreground shadow-elevation-1 hover:bg-accent/90",
        ghost: "text-foreground hover:bg-primary/10 hover:text-primary",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 rounded-lg px-3",
        lg: "h-11 rounded-xl px-8 text-[0.95rem]",
        icon: "pw-tap-icon h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
