/**
 * The changelog masthead: the convergence seam motif at hero scale. The two retrieval legs the whole
 * site is built on — the crowd (warm --cultural) and the sound (cool --audio) — sweep in and braid
 * into a single fused --seam rail, which descends straight into the first timeline node below (the
 * latest change). There is deliberately NO separate node/label here: the latest change IS the present
 * Doppel, so a "Doppel today" node would just duplicate the first entry's node.
 *
 * IN REGISTER (invariant #8 / DECISIONS 2026-06-15): the two streams mean the crowd and the sound —
 * their meaning everywhere else on the site — never repurposed to mean engine-vs-site work.
 *
 * HONEST (invariant #8 / DECISIONS 2026-06-18): fully rendered and static (idle=final), so SSR / no-JS
 * show the complete truthful state, and there is NO pulse — the "live" pulse idiom belongs only to the
 * genuinely-live ops-panel marker.
 *
 * GLOW: each leg is a crisp bright core stroke plus a soft blurred bloom of the same color behind it
 * (real emitted light), not a faded outline. The fused rail exits at the bottom (x=36) so, inside the
 * page's content column, it lines up with the timeline spine just below.
 */
export function ConvergenceMasthead() {
  return (
    <svg
      viewBox="0 0 700 300"
      role="img"
      aria-label="The crowd and the sound braiding into one fused result"
      className="h-auto w-full"
    >
      <defs>
        <filter id="cl-bloom" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="6" />
        </filter>
      </defs>

      {/* soft colored bloom (blurred copies — the emitted light). `changelog-stream-glow` pulses the
          halo opacity in step with the node radiate (motion-safe; reduced-motion rests on full glow). */}
      <g className="changelog-stream-glow" filter="url(#cl-bloom)" fill="none" strokeLinecap="round">
        <path d="M24 18 C 18 120, 24 200, 36 252" stroke="var(--cultural)" strokeOpacity="0.55" strokeWidth="8" />
        <path d="M684 18 C 420 44, 118 156, 36 252" stroke="var(--audio)" strokeOpacity="0.55" strokeWidth="8" />
        <path d="M36 252 L 36 300" stroke="var(--seam)" strokeOpacity="0.7" strokeWidth="7" />
      </g>

      {/* crisp bright cores */}
      <g fill="none" strokeLinecap="round">
        <path d="M24 18 C 18 120, 24 200, 36 252" stroke="var(--cultural)" strokeWidth="2.6" />
        <path d="M684 18 C 420 44, 118 156, 36 252" stroke="var(--audio)" strokeWidth="2.6" />
        <path d="M36 252 L 36 300" stroke="var(--seam)" strokeWidth="2.4" />
      </g>

      {/* labels (telemetry voice) */}
      <text x="40" y="15" className="fill-cultural font-mono" style={{ fontSize: "13.5px", letterSpacing: "0.04em" }}>
        the crowd
      </text>
      <text x="680" y="15" textAnchor="end" className="fill-audio font-mono" style={{ fontSize: "13.5px", letterSpacing: "0.04em" }}>
        the sound
      </text>
    </svg>
  );
}
