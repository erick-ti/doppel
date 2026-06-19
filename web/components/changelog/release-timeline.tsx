import { Fragment } from "react";

import { prUrl, RELEASES } from "@/lib/changelog";
import { cn, linkFocus } from "@/lib/utils";

/**
 * The PR receipts for a release. Up to 3 PRs render as individual links; a longer run renders as a
 * "#first–#last" range (both ends linked) so the row stays readable. With no PRs, a plain `caption`
 * shows instead (e.g. "latest version" for the unmerged page, "the idea" for the genesis) — never a
 * fake/guessed link.
 */
function PrLinks({ prs, caption }: { prs: number[]; caption?: string }) {
  if (prs.length === 0) {
    return caption ? (
      <span className="text-muted-foreground/70 font-mono text-[11px]">{caption}</span>
    ) : null;
  }
  const range = prs.length > 3;
  const shown = range ? [prs[0], prs[prs.length - 1]] : prs;
  return (
    <span className="flex items-center gap-1.5 font-mono text-[12.5px]">
      {shown.map((n, i) => (
        <Fragment key={n}>
          {range && i === 1 && (
            <span className="text-muted-foreground/50" aria-hidden>
              –
            </span>
          )}
          <a
            href={prUrl(n)}
            target="_blank"
            rel="noopener noreferrer"
            className={cn("text-seam transition-opacity hover:opacity-80", linkFocus)}
          >
            #{n}
          </a>
        </Fragment>
      ))}
      <span className="sr-only"> (opens the pull request on GitHub in a new tab)</span>
    </span>
  );
}

/**
 * The seam-spine timeline: a single --seam rail (the fused through-line, continuing the masthead's
 * braided streams) with a node per release. Newest first, down to the genesis at the root. The FIRST
 * node is the radiant convergence point — where the crowd and the sound currently fuse — so the latest
 * change is the single "present" marker (no duplicate "today" node above it). Fully static / SSR.
 */
export function ReleaseTimeline({ className }: { className?: string }) {
  return (
    <ol className={cn("relative list-none", className)}>
      {/* the seam spine — the fused through-line, continuing down from the masthead rail */}
      <span
        className="from-seam/60 to-seam/5 pointer-events-none absolute top-0 bottom-3 left-[37px] w-px bg-gradient-to-b"
        aria-hidden
      />
      {RELEASES.map((r, idx) => {
        const isLatest = idx === 0;
        return (
          <li key={r.id} className="relative pb-9 pl-[68px] last:pb-0">
            {isLatest && (
              // radial bloom behind the newest node — the streams' fusion point radiating light.
              // `changelog-node-bloom` adds the motion-safe --seam radiate pulse (globals.css);
              // reduced-motion / no-JS rest on the static gradient below (idle=final).
              <span
                className="changelog-node-bloom pointer-events-none absolute top-[-9px] left-[15px] size-11 rounded-full"
                style={{
                  background:
                    "radial-gradient(circle, color-mix(in oklab, var(--seam) 50%, transparent) 0%, transparent 68%)",
                }}
                aria-hidden
              />
            )}
            <span
              className={cn(
                "bg-seam ring-background absolute rounded-full ring-2",
                isLatest ? "changelog-node-core top-[5px] left-[29px] size-4" : "top-[7px] left-[31px] size-3",
              )}
              style={{
                boxShadow: isLatest
                  ? "0 0 12px 1px color-mix(in oklch, var(--seam) 70%, transparent)"
                  : "0 0 10px 1px color-mix(in oklab, var(--seam) 70%, transparent)",
              }}
              aria-hidden
            />
            <div className="mb-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <time dateTime={r.date} className="text-muted-foreground font-mono text-[12.5px] tabular-nums">
                {r.date}
              </time>
              {r.track && (
                <span className="text-muted-foreground border-border rounded border px-1.5 py-px font-mono text-[10.5px] tracking-[0.08em] uppercase">
                  {r.version ? `${r.track} · ${r.version}` : r.track}
                </span>
              )}
              <PrLinks prs={r.prs} caption={r.caption} />
            </div>
            <h2 className="font-display text-lg font-semibold tracking-tight sm:text-xl">{r.title}</h2>
            <p className="text-muted-foreground mt-1 max-w-[60ch] text-[15px] leading-relaxed">{r.summary}</p>
            {r.highlights && (
              // Scannable stack + metrics for a technical reader — neutral facts in the telemetry
              // (mono) voice, kept secondary to the plain summary. A short --seam lead-in ties it
              // to the motif. NEVER recruiter/audience framing here (invariant #6).
              <p className="text-muted-foreground/70 mt-2 max-w-[62ch] font-mono text-[11.5px] leading-relaxed">
                <span className="bg-seam/60 mr-2 inline-block h-px w-3 align-middle" aria-hidden />
                {r.highlights.join(" · ")}
              </p>
            )}
          </li>
        );
      })}
    </ol>
  );
}
