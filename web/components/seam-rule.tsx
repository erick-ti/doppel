import { cn } from "@/lib/utils";

/**
 * A section divider carrying the convergence seam motif at the smallest scale: a warm cultural
 * hairline and a cool audio hairline meeting at a glowing --seam node. Used between major sections so
 * the signature recurs through the page, not just in the hero.
 */
export function SeamRule({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center", className)} aria-hidden>
      <span className="via-cultural/40 h-px flex-1 bg-gradient-to-r from-transparent to-transparent" />
      <span className="bg-seam mx-2 size-1.5 rounded-full" style={{ boxShadow: "0 0 8px var(--seam)" }} />
      <span className="via-audio/40 h-px flex-1 bg-gradient-to-r from-transparent to-transparent" />
    </div>
  );
}
