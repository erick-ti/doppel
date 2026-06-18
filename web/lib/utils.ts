import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind class lists, resolving conflicts (shadcn convention). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * The house focus treatment for standalone navigational/external links, mirroring the Button
 * primitive's `focus-visible:ring-[3px]`. Plain links carry only hover + transition-colors otherwise,
 * which leaves keyboard users with a faint UA outline against the warm-charcoal palette (WCAG 2.4.7).
 * Append via `cn(...)` so every link shares one definition instead of drifting per file.
 */
export const linkFocus =
  "rounded-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50";
