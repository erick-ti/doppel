import { Lock, Search } from "lucide-react";

/**
 * The disabled free-text seed box (server component, no client JS).
 *
 * Honest by design: arbitrary live input would hit the ~12-min cold path (resolve + embed a fresh
 * candidate set), so there is no public live endpoint — the showcase serves frozen real runs instead.
 * The box looks like the real entry point but is non-interactive, with the reason stated inline and a
 * native-tooltip `title` for the hover. It points at the curated gallery rather than a route that does
 * not exist yet (the recorded cold-run deep-dive is a later phase).
 */
export function SeedBox() {
  const reason =
    "Arbitrary live input takes ~12 min cold (resolve + embed a fresh candidate set), so there is no public live endpoint. Browse the curated runs below — each is real, frozen pipeline output.";

  return (
    <div className="mt-10 max-w-xl">
      <div
        className="bg-card/40 text-muted-foreground flex items-center gap-3 rounded-xl border border-dashed px-4 py-3"
        title={reason}
      >
        <Search className="size-4 shrink-0" aria-hidden />
        <span className="flex-1 truncate text-sm select-none">
          Enter a song… (e.g. “Blinding Lights — The Weeknd”)
        </span>
        <span className="text-muted-foreground/80 inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[11px]">
          <Lock className="size-3" aria-hidden />
          disabled
        </span>
      </div>
      <p className="text-muted-foreground mt-2 text-xs leading-relaxed">
        Live arbitrary input takes ~12&nbsp;min cold, so there’s no public
        endpoint — the engine never runs on this site.{" "}
        <a
          href="#seed-gallery"
          className="text-foreground underline decoration-dotted underline-offset-2"
        >
          Browse the curated runs
        </a>{" "}
        below — every one is real, frozen pipeline output.
      </p>
    </div>
  );
}
