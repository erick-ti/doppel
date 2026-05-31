import { Braces } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

/**
 * "View raw JSON" — un-fakeable proof for the technical reviewer that every rendered number is a
 * field on real persisted pipeline output. Invisible to the non-technical visitor until opened.
 */
export function RawJsonDialog({
  data,
  title,
  description,
  triggerLabel = "View raw JSON",
}: {
  data: unknown;
  title: string;
  description?: string;
  triggerLabel?: string;
}) {
  return (
    <Dialog>
      <DialogTrigger className="text-muted-foreground hover:text-foreground focus-visible:ring-ring focus-visible:ring-offset-background -mr-1 inline-flex items-center gap-1.5 rounded px-1 py-1.5 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none">
        <Braces className="size-3.5" aria-hidden />
        {triggerLabel}
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <pre className="bg-background max-h-[60vh] overflow-auto rounded-lg border p-4 font-mono text-xs leading-relaxed">
          {JSON.stringify(data, null, 2)}
        </pre>
      </DialogContent>
    </Dialog>
  );
}
