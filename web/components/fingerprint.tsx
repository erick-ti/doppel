/**
 * Renders a seed's earned SIGNAL FINGERPRINT (lib/fingerprint.ts) as a deterministic dual SPECTRUM —
 * the data-derived replacement for the letter-on-a-gradient cover and a per-row glyph in the picker.
 *
 * Each result is one column: a cool AUDIO bar rising from the centerline (band-normalized CLAP cosine)
 * over a warm CULTURAL bar dropping below it (batch-relative RRF). Column WIDTHS are driven by the
 * real cultural-consensus value (stronger consensus = wider) plus a per-seed deterministic jitter, so
 * the bars are uneven and dense like raw spectra — not a uniform equalizer. Bar HEIGHTS are always the
 * real values. No hooks, no Math.random — same seed always renders the same mark (server or client).
 */
import type { FingerprintData } from "@/lib/fingerprint";

/** FNV-1a string hash -> seed for the deterministic per-seed jitter. */
function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** mulberry32 PRNG — deterministic, seeded; only drives cosmetic width/spacing texture. */
function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Lay out N columns across [pad, W-pad] with widths driven by cultural consensus + seeded jitter. */
function columns(data: FingerprintData, W: number, pad: number) {
  const rng = mulberry32(hashStr(data.slug));
  const weights = data.audio.map((_, i) => 0.45 + (data.cultural[i] ?? 0) * 1.3 + rng() * 0.8);
  const total = weights.reduce((s, w) => s + w, 0) || 1;
  const availW = W - pad * 2;
  let x = pad;
  return weights.map((w) => {
    const colW = (w / total) * availW;
    const barW = Math.max(1.5, colW * (0.5 + rng() * 0.28));
    const bx = x + (colW - barW) / 2;
    x += colW;
    return { bx, barW };
  });
}

function Hatch({ id }: { id: string }) {
  return (
    <defs>
      <pattern id={id} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <line x1="0" y1="0" x2="0" y2="5" className="stroke-muted-foreground/40" strokeWidth="1" />
      </pattern>
    </defs>
  );
}

/** Full card cover (16:10): a dense dual-spectrum, audio above / cultural below the seam centerline. */
function Cover({ data }: { data: FingerprintData }) {
  const W = 240;
  const H = 150;
  const midY = 84;
  const padX = 12;
  const upMax = midY - 14;
  const downMax = H - midY - 14;
  const cols = columns(data, W, padX);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <Hatch id={`fp-${data.slug}`} />
      <line x1={padX} y1={midY} x2={W - padX} y2={midY} className="stroke-seam/50" strokeWidth="1.5" />

      {data.audio.map((a, i) => {
        const { bx, barW } = cols[i];
        const cul = data.cultural[i] ?? 0;
        const isHnsw = data.rows[i]?.sources.includes("hnsw");
        const upH = (a ?? 0) * upMax;
        const downH = cul * downMax;
        const fused = data.fused[i] ?? 0;
        return (
          <g key={i}>
            {data.degraded || a == null ? (
              <rect x={bx} y={midY - upMax} width={barW} height={upMax} fill={`url(#fp-${data.slug})`} />
            ) : (
              <rect
                x={bx}
                y={midY - upH}
                width={barW}
                height={Math.max(1, upH)}
                rx="0.5"
                className={isHnsw ? "fill-audio-deep" : "fill-audio"}
                opacity={0.55 + fused * 0.45}
              />
            )}
            <rect
              x={bx}
              y={midY + 1}
              width={barW}
              height={Math.max(1, downH)}
              rx="0.5"
              className="fill-cultural"
              opacity={0.5 + cul * 0.4}
            />
            {i === 0 && <circle cx={bx + barW / 2} cy={midY} r="2.5" className="fill-seam" />}
          </g>
        );
      })}
    </svg>
  );
}

/** Compact spark for picker rows (~92×26): the same dual spectrum, miniaturized. */
function Spark({ data }: { data: FingerprintData }) {
  const W = 92;
  const H = 26;
  const midY = 14;
  const upMax = midY - 2;
  const downMax = H - midY - 2;
  const cols = columns(data, W, 2);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-6 w-[92px] shrink-0" preserveAspectRatio="none" aria-hidden>
      <Hatch id={`spk-${data.slug}`} />
      <line x1={2} y1={midY} x2={W - 2} y2={midY} className="stroke-seam/45" strokeWidth="0.75" />
      {data.audio.map((a, i) => {
        const { bx, barW } = cols[i];
        const cul = data.cultural[i] ?? 0;
        const isHnsw = data.rows[i]?.sources.includes("hnsw");
        return (
          <g key={i}>
            {data.degraded || a == null ? (
              <rect x={bx} y={midY - upMax} width={barW} height={upMax} fill={`url(#spk-${data.slug})`} />
            ) : (
              <rect
                x={bx}
                y={midY - (a ?? 0) * upMax}
                width={barW}
                height={Math.max(0.75, (a ?? 0) * upMax)}
                className={isHnsw ? "fill-audio-deep" : "fill-audio"}
              />
            )}
            <rect x={bx} y={midY + 0.5} width={barW} height={Math.max(0.75, cul * downMax)} className="fill-cultural/80" />
          </g>
        );
      })}
    </svg>
  );
}

export function Fingerprint({
  data,
  variant = "cover",
}: {
  data: FingerprintData;
  variant?: "cover" | "spark";
}) {
  return variant === "spark" ? <Spark data={data} /> : <Cover data={data} />;
}
