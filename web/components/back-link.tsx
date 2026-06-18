import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { cn, linkFocus } from "@/lib/utils";

/**
 * The single "back" affordance — one definition the way Button/SeamRule are, replacing the
 * byte-identical ad-hoc back-link string that had been copy-pasted across the result, how-it-works,
 * deep-dive, and status routes (a hover/spacing tweak silently desynced one from the others).
 */
export function BackLink({
  href = "/",
  label = "All songs",
  className,
}: {
  href?: string;
  label?: string;
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1.5 text-sm transition-colors",
        linkFocus,
        className,
      )}
    >
      <ArrowLeft className="size-4" aria-hidden />
      {label}
    </Link>
  );
}
