import Link from "next/link";

/** A 404 in the engine's voice: the two legs never converged on this seed — the seam stays dark. */
export default function NotFound() {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col items-center gap-6 px-5 py-28 text-center">
      <svg viewBox="0 0 220 64" className="w-52" aria-hidden fill="none">
        <path
          d="M2 16 C70 16, 84 32, 110 32"
          className="stroke-cultural/60"
          strokeWidth="2"
          strokeLinecap="round"
        />
        {/* the audio leg never lands — dashed, falling short of the node */}
        <path
          d="M218 48 C150 48, 136 32, 116 32"
          className="stroke-audio/50"
          strokeWidth="2"
          strokeLinecap="round"
          strokeDasharray="2 7"
        />
        <circle cx="110" cy="32" r="3.5" className="fill-muted-foreground/40" />
      </svg>

      <p className="text-muted-foreground font-mono text-[11px] tracking-[0.18em] uppercase">
        404 · no signal
      </p>
      <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">
        This seed never reached the engine
      </h1>
      <p className="text-muted-foreground max-w-md leading-relaxed">
        That run isn&rsquo;t in the analyzed library — the two retrieval legs never converged on it.
        Pick a recorded seed from the console and watch the rail light up instead.
      </p>
      <Link
        href="/"
        className="text-seam hover:text-seam/80 inline-flex items-center gap-1.5 font-mono text-sm transition-colors"
      >
        ← back to the console
      </Link>
    </div>
  );
}
