"use client";

import { cva, type VariantProps } from "class-variance-authority";
import { motion } from "framer-motion";
import { IconArrowRight } from "@tabler/icons-react";

const button = cva(
  "inline-flex items-center justify-center gap-2 font-medium transition-all duration-200 cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber",
  {
    variants: {
      variant: {
        solid:
          "bg-amber text-charcoal hover:bg-amber-light active:scale-[0.98]",
        outline:
          "border-2 border-amber text-amber bg-transparent hover:bg-amber/10 active:scale-[0.98]",
        ghost:
          "bg-transparent text-cream hover:bg-cream/5 active:scale-[0.98]",
        "ghost-dark":
          "bg-transparent text-charcoal hover:bg-charcoal/5 active:scale-[0.98]",
        soft:
          "bg-amber/10 text-amber hover:bg-amber/20 active:scale-[0.98]",
        "solid-white":
          "bg-cream text-charcoal hover:bg-warm-white active:scale-[0.98]",
        "outline-white":
          "border-2 border-cream text-cream bg-transparent hover:bg-cream/10 active:scale-[0.98]",
        underline:
          "bg-transparent text-amber underline underline-offset-4 hover:text-amber-light active:scale-[0.98] px-0 py-0",
      },
      size: {
        sm: "px-4 py-2 text-sm",
        md: "px-6 py-3 text-base",
        lg: "px-8 py-4 text-lg",
      },
      shape: {
        sharp: "rounded-none",
        subtle: "rounded-sm",
      },
    },
    defaultVariants: {
      variant: "solid",
      size: "md",
      shape: "sharp",
    },
  }
);

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof button> & {
    arrow?: boolean;
    href?: string;
    shimmer?: boolean;
  };

export default function Button({
  children,
  variant,
  size,
  shape,
  arrow,
  shimmer,
  className,
  href,
  ...props
}: ButtonProps) {
  const classes = button({ variant, size, shape, className });
  const shimmerClass = shimmer ? " shimmer-btn" : "";

  if (href) {
    return (
      <motion.a
        href={href}
        className={classes + shimmerClass}
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.98 }}
      >
        {children}
        {arrow && <IconArrowRight size={18} stroke={2} />}
      </motion.a>
    );
  }

  return (
    <motion.button
      className={classes + shimmerClass}
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      {...(props as any)}
    >
      {children}
      {arrow && <IconArrowRight size={18} stroke={2} />}
    </motion.button>
  );
}
