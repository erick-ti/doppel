import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * The neutral bench/instrument container — a flat, shadow-free bordered surface matching the ad-hoc
 * `rounded-xl border` panels used across the app (the one card convention). Only <Card> is consumed
 * (seed-card, result-card); the shadcn CardHeader/Title/Description/Content/Footer sub-parts were
 * never imported and were removed rather than left as stock scaffolding.
 */
function Card({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card"
      className={cn(
        "bg-card text-card-foreground flex flex-col gap-6 rounded-xl border py-6",
        className,
      )}
      {...props}
    />
  );
}

export { Card };
