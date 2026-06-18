/**
 * THE SEAM — the dominant, signature instrument of the landing.
 *
 * Two retrieval streams braid into one: warm CULTURAL strands and cool AUDIO strands meet at a glowing
 * convergence node, and a bright --seam rail descends carrying the FUSED shortlist. Pure SVG; the whole
 * drawing is parameterized by one scalar `p` (0..1) so the parent's single RAF clock owns it (and the
 * folded stages + shortlist) — they can never disagree.
 *
 * Two geometries: `wide` (desktop, streams from the side edges) and `tall` (mobile, streams pour from
 * the top corners into a vertical rail) — so the signature stays dominant on a phone, never letterboxed.
 * A faint scope grid + calibration ticks + a node lens give it instrument materiality (not a diagram).
 *
 * idle = final: at p = 1 the instrument is fully welded (every strand drawn, node lit, rail complete),
 * which is exactly what SSR / no-JS / reduced-motion render. Motion only ever rewinds p post-mount.
 * The slow opacity "breathing" is pure CSS, gated to motion-safe (globals.css).
 */

type Orientation = "wide" | "tall";

interface Geometry {
  w: number;
  h: number;
  nodeX: number;
  nodeY: number;
  warm: string[];
  cool: string[];
  railEndY: number;
  gridY: number[];
  tickX: number[];
}

function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

const WIDE: Geometry = (() => {
  const w = 900;
  const h = 300;
  const nodeX = 450;
  const nodeY = 122;
  const ys = Array.from({ length: 7 }, (_, i) => 22 + i * 28);
  return {
    w,
    h,
    nodeX,
    nodeY,
    warm: ys.map((y) => `M 0 ${y} C 175 ${y}, ${nodeX - 135} ${nodeY}, ${nodeX} ${nodeY}`),
    cool: ys.map((y) => `M ${w} ${y} C ${w - 175} ${y}, ${nodeX + 135} ${nodeY}, ${nodeX} ${nodeY}`),
    railEndY: h - 16,
    gridY: [60, 122, 184, 246],
    tickX: Array.from({ length: 19 }, (_, i) => 20 + i * 46),
  };
})();

const TALL: Geometry = (() => {
  // viewBox aspect = 4/5, matched exactly by the container so it fills (no mobile letterbox).
  const w = 400;
  const h = 500;
  const nodeX = 200;
  const nodeY = 188;
  const warmStarts = [12, 56, 100, 144, 188];
  const coolStarts = [212, 256, 300, 344, 388];
  return {
    w,
    h,
    nodeX,
    nodeY,
    warm: warmStarts.map((x) => `M ${x} 0 C ${x} 96, ${nodeX - 95} ${nodeY}, ${nodeX} ${nodeY}`),
    cool: coolStarts.map((x) => `M ${x} 0 C ${x} 96, ${nodeX + 95} ${nodeY}, ${nodeX} ${nodeY}`),
    railEndY: h - 18,
    gridY: [70, 140, 300, 400, 460],
    tickX: Array.from({ length: 9 }, (_, i) => 16 + i * 46),
  };
})();

export function Seam({
  p,
  degraded = false,
  orientation = "wide",
  railFormed = true,
}: {
  p: number;
  degraded?: boolean;
  orientation?: Orientation;
  /** The FUSED output rail forms only when the recorded `results` (fuse) stage completes — the parent
   *  gates this on real stage timing, NEVER raw teaser progress (recorded-replay honesty). It eases in
   *  via CSS when it flips. The streams/node before it are a non-output convergence effect. */
  railFormed?: boolean;
}) {
  const g = orientation === "tall" ? TALL : WIDE;
  const draw = smoothstep(0, 0.55, p);
  const ignite = smoothstep(0.4, 0.74, p);
  const rail = railFormed ? 1 : 0;
  const railEase =
    "stroke-dashoffset 0.6s var(--ease-settle), opacity 0.6s var(--ease-settle)";
  const fadeEase = "opacity 0.6s var(--ease-settle)";
  const strandDash = { strokeDasharray: 1, strokeDashoffset: 1 - draw } as const;
  const uid = orientation;

  return (
    <svg viewBox={`0 0 ${g.w} ${g.h}`} className="h-full w-full" preserveAspectRatio="xMidYMid meet" aria-hidden>
      <defs>
        <filter id={`seam-glow-${uid}`} x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="6" />
        </filter>
        <filter id={`seam-glow-strong-${uid}`} x="-120%" y="-120%" width="340%" height="340%">
          <feGaussianBlur stdDeviation="11" />
        </filter>
      </defs>

      {/* instrument materiality: a faint scope grid + edge calibration ticks (a faceplate, not a diagram) */}
      <g className="stroke-foreground/[0.045]" strokeWidth="1" vectorEffect="non-scaling-stroke">
        {g.gridY.map((y) => (
          <line key={`gy-${y}`} x1={8} y1={y} x2={g.w - 8} y2={y} />
        ))}
      </g>
      <g className="stroke-foreground/15" strokeWidth="1" vectorEffect="non-scaling-stroke">
        {g.tickX.map((x, i) => (
          <line key={`tk-${x}`} x1={x} y1={8} x2={x} y2={i % 4 === 0 ? 16 : 12} />
        ))}
        {g.tickX.map((x, i) => (
          <line key={`tb-${x}`} x1={x} y1={g.h - 8} x2={x} y2={g.h - (i % 4 === 0 ? 16 : 12)} />
        ))}
      </g>

      {/* the seam axis */}
      <line x1={g.nodeX} y1={8} x2={g.nodeX} y2={g.h - 8} className="stroke-seam/25" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />

      {/* CULTURAL stream (warm) */}
      <g>
        {g.warm.map((d, i) => (
          <path
            key={i}
            d={d}
            pathLength={1}
            className="fill-none stroke-cultural"
            strokeWidth={i % 2 === 0 ? 2.4 : 1.6}
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
            style={{ ...strandDash, opacity: 0.55 + (i % 2) * 0.25 }}
          />
        ))}
      </g>

      {/* AUDIO stream (cool). On a degraded run there is no audio rerank -> dimmed (now authoritative,
          no opacity-animating CSS class to override it). */}
      <g style={{ opacity: degraded ? 0.22 : 1 }}>
        {g.cool.map((d, i) => (
          <path
            key={i}
            d={d}
            pathLength={1}
            className="fill-none stroke-audio"
            strokeWidth={i % 2 === 0 ? 2.4 : 1.6}
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
            style={{ ...strandDash, opacity: 0.55 + (i % 2) * 0.25 }}
          />
        ))}
      </g>

      {/* FUSED rail — glow underlay + core */}
      <line
        x1={g.nodeX}
        y1={g.nodeY}
        x2={g.nodeX}
        y2={g.railEndY}
        pathLength={1}
        className="stroke-seam"
        strokeWidth="9"
        strokeLinecap="round"
        filter={`url(#seam-glow-${uid})`}
        style={{ strokeDasharray: 1, strokeDashoffset: 1 - rail, opacity: 0.5 * rail, transition: railEase }}
      />
      <line
        x1={g.nodeX}
        y1={g.nodeY}
        x2={g.nodeX}
        y2={g.railEndY}
        pathLength={1}
        className="stroke-seam"
        strokeWidth="3.5"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
        style={{ strokeDasharray: 1, strokeDashoffset: 1 - rail, transition: railEase }}
      />
      {[0.4, 0.66, 0.9].map((f) => (
        <line
          key={f}
          x1={g.nodeX - 6}
          y1={g.nodeY + f * (g.railEndY - g.nodeY)}
          x2={g.nodeX + 6}
          y2={g.nodeY + f * (g.railEndY - g.nodeY)}
          className="stroke-seam/70"
          strokeWidth="1.5"
          vectorEffect="non-scaling-stroke"
          style={{ opacity: rail, transition: fadeEase }}
        />
      ))}
      <circle cx={g.nodeX} cy={g.railEndY} r={4.5} className="fill-seam" style={{ opacity: rail, transition: fadeEase }} />

      {/* the convergence node — lens depth: outer bloom, ring, core. The two BLUR-FILTERED circles keep
          a FIXED radius and animate only opacity — a changing radius on a filtered element forces the
          browser to recompute the filter region and re-rasterize the blur every frame (the teaser's
          heaviest paint). The size "ignite" pulse rides the unfiltered core below, which is cheap. */}
      <circle cx={g.nodeX} cy={g.nodeY} r={34} className="fill-seam seam-node-glow" filter={`url(#seam-glow-strong-${uid})`} style={{ opacity: 0.35 * ignite }} />
      <circle cx={g.nodeX} cy={g.nodeY} r={18} className="fill-none stroke-seam/50" strokeWidth="1" vectorEffect="non-scaling-stroke" style={{ opacity: ignite }} />
      <circle cx={g.nodeX} cy={g.nodeY} r={16} className="fill-seam" filter={`url(#seam-glow-${uid})`} style={{ opacity: 0.45 * ignite }} />
      <circle cx={g.nodeX} cy={g.nodeY} r={9 + 3 * ignite} className="fill-seam" style={{ opacity: 0.3 + 0.7 * ignite }} />
      <circle cx={g.nodeX} cy={g.nodeY} r={4} className="fill-background" style={{ opacity: ignite }} />
    </svg>
  );
}
