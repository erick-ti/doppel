/**
 * Eval-evidence panels for /how-it-works — rendered straight from the frozen `eval-evidence.ts`
 * figures (one real diagnostic run). Three panels:
 *   1. per-genre audio-cosine ranges  — "works across the whole map"
 *   2. audio vs vibe-text band separation — why fusion min-max-normalizes each leg first
 *   3. the N=75 ablation — CLAP visibly reshuffles the cultural shortlist
 *
 * Every panel carries the DIAGNOSTIC disclaimer: no ground-truth label, not precision/recall, no
 * competitor comparison. Bars map the real cosine onto a fixed [0.3, 1.0] perceptual window (the same
 * honest band the per-row score breakdown uses) so they never read as percentages.
 */
import {
  ABLATION,
  ABLATION_EXAMPLES,
  AUDIO_BAND,
  EVAL_HEADLINE,
  EVAL_PROVENANCE,
  GENRE_BANDS,
  VIBE_BAND,
} from "@/lib/eval-evidence";

/** Map a cosine in the perceptual [0.3, 1.0] window onto a 0-100% bar position (clamped). */
const BAND_MIN = 0.3;
const BAND_MAX = 1.0;
const pct = (v: number) =>
  Math.min(100, Math.max(0, ((v - BAND_MIN) / (BAND_MAX - BAND_MIN)) * 100));

function DiagnosticTag() {
  return (
    <span className="border-border text-muted-foreground inline-flex w-fit items-center rounded-full border px-2 py-0.5 font-mono text-[10px] tracking-wide uppercase">
      diagnostic · no ground truth
    </span>
  );
}

function PanelShell({
  title,
  blurb,
  children,
}: {
  title: string;
  blurb: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border p-5">
      <div className="mb-4 flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-semibold tracking-tight">{title}</h3>
          <DiagnosticTag />
        </div>
        <p className="text-muted-foreground text-sm leading-relaxed">{blurb}</p>
      </div>
      {children}
    </div>
  );
}

/** Panel 1: per-genre audio-cosine ranges as floating range bars on the shared [0.3, 1.0] axis. */
function GenreRanges() {
  return (
    <PanelShell
      title="Audio similarity holds across the whole map"
      blurb="Raw CLAP audio cosine for each genre's top-10 neighbours. Jazz clusters tightest and highest; electronic spreads lowest — but every genre lands well inside the music band, which is the cross-genre coverage claim."
    >
      <div className="flex flex-col gap-2.5">
        {GENRE_BANDS.map((g) => (
          <div
            key={g.genre}
            className="grid grid-cols-[5.5rem_1fr_auto] items-center gap-x-3"
            title={`${g.label}: ${g.seeds.join(", ")}`}
          >
            <span className="text-sm font-medium">{g.label}</span>
            <div className="bg-muted/50 relative h-2 w-full overflow-hidden rounded-full">
              <div
                className="bg-audio absolute inset-y-0 rounded-full"
                style={{ left: `${pct(g.min)}%`, width: `${pct(g.max) - pct(g.min)}%` }}
                aria-hidden
              />
            </div>
            <span className="text-muted-foreground font-mono text-xs tabular-nums">
              {g.min.toFixed(3)}–{g.max.toFixed(3)}
            </span>
          </div>
        ))}
      </div>
      <p className="text-muted-foreground mt-3 font-mono text-[11px]">
        axis: cosine 0.30 → 1.00 · the perceptual music band
      </p>
    </PanelShell>
  );
}

/** Panel 2: the two legs' bands on one axis — visibly disjoint, so fusion must normalize first. */
function BandSeparation() {
  const legs = [
    { label: "Audio cosine", band: AUDIO_BAND, cls: "bg-audio", note: "how alike two tracks sound" },
    { label: "Vibe-text cosine", band: VIBE_BAND, cls: "bg-cultural", note: "text→audio match (deliberately weak leg)" },
  ];
  return (
    <PanelShell
      title="The two legs live in different ranges"
      blurb="Audio cosine clusters high; the text encoder is a deliberately weak signal that clusters low. They barely overlap — which is exactly why fusion min-max-normalizes each leg within the batch before weighting (α=0.7 / β=0.3). You can't fuse raw values on different scales."
    >
      <div className="flex flex-col gap-4">
        {legs.map((l) => (
          <div key={l.label} className="grid grid-cols-[7rem_1fr_auto] items-center gap-x-3">
            <span className="text-sm font-medium">{l.label}</span>
            <div className="bg-muted/50 relative h-2.5 w-full overflow-hidden rounded-full">
              <div
                className={`${l.cls} absolute inset-y-0 rounded-full`}
                style={{ left: `${pct(l.band.min)}%`, width: `${pct(l.band.max) - pct(l.band.min)}%` }}
                aria-hidden
              />
            </div>
            <span className="text-muted-foreground font-mono text-xs tabular-nums">
              {l.band.min.toFixed(3)}–{l.band.max.toFixed(3)}
            </span>
          </div>
        ))}
      </div>
      <p className="text-muted-foreground mt-3 text-xs">
        Same 0.30–1.00 axis. The gap between the bars is the whole argument for normalize-then-fuse.
      </p>
    </PanelShell>
  );
}

/** Panel 3: the ablation — how far CLAP moves the cultural order, with real reranked top-3s. */
function Ablation() {
  return (
    <PanelShell
      title="CLAP reshuffles the cultural shortlist"
      blurb={`Comparing the pure cultural (RRF) order to the CLAP-reranked order at k=${ABLATION.k}: the two share a median of just ${ABLATION.overlapMedian.toFixed(1)} of their top ${ABLATION.k} (range ${ABLATION.overlapMin.toFixed(1)}–${ABLATION.overlapMax.toFixed(1)}), with a median rank displacement of ${ABLATION.displacementMedian.toFixed(1)} places (range ${ABLATION.displacementMin.toFixed(1)}–${ABLATION.displacementMax.toFixed(1)}). The audio leg is doing real work — it isn't a pass-through of the cultural ranking.`}
    >
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="bg-muted/40 flex-1 rounded-lg border p-3">
          <div className="text-audio font-mono text-2xl font-semibold tabular-nums">
            {ABLATION.overlapMedian.toFixed(1)}
          </div>
          <div className="text-muted-foreground text-xs">
            median top-{ABLATION.k} overlap · RRF vs CLAP order
          </div>
        </div>
        <div className="bg-muted/40 flex-1 rounded-lg border p-3">
          <div className="text-audio font-mono text-2xl font-semibold tabular-nums">
            {ABLATION.displacementMedian.toFixed(1)}
          </div>
          <div className="text-muted-foreground text-xs">
            median rank displacement · places moved
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        {ABLATION_EXAMPLES.map((ex) => {
          const [title, artist] = ex.seed.split(" — ");
          return (
            <div key={ex.seed} className="border-border/60 rounded-lg border p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <span className="text-sm font-medium">
                  {title}
                  <span className="text-muted-foreground font-normal"> · {artist}</span>
                </span>
                <span className="text-muted-foreground font-mono text-[11px] tabular-nums">
                  overlap {ex.overlap.toFixed(1)} · disp {ex.displacement}
                </span>
              </div>
              <ol className="text-muted-foreground mt-1.5 flex flex-col gap-0.5 text-sm">
                {ex.clapTop3.map((t, i) => (
                  <li key={t} className="flex gap-2">
                    <span className="text-audio font-mono text-xs tabular-nums">
                      {i + 1}
                    </span>
                    {t}
                  </li>
                ))}
              </ol>
            </div>
          );
        })}
      </div>
    </PanelShell>
  );
}

export function EvalEvidence() {
  return (
    <section className="flex flex-col gap-5">
      <div className="max-w-2xl">
        <h2 className="text-2xl font-semibold tracking-tight">Does the audio leg earn its keep?</h2>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          These panels render straight from one frozen diagnostic run
          (<span className="font-mono text-xs">{EVAL_PROVENANCE.run}</span>) over the full{" "}
          {EVAL_HEADLINE.seedsTotal}-seed benchmark set. It is a coverage-and-behaviour run, not
          precision/recall — there is no ground-truth &ldquo;good vibe match&rdquo; label, so nothing here
          measures or claims to beat any competitor. It only shows what the engine does.
        </p>
        <div className="bg-card/50 mt-4 inline-flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border px-4 py-2 font-mono text-sm">
          <span className="font-semibold tabular-nums">
            {EVAL_HEADLINE.seedsAudioScored}/{EVAL_HEADLINE.seedsTotal}
          </span>
          <span className="text-muted-foreground">
            seeds audio-scored across {EVAL_HEADLINE.genres} genres
          </span>
          <span className="text-muted-foreground/50">·</span>
          <span className="text-muted-foreground">median resolve found-ratio</span>
          <span className="font-semibold tabular-nums">
            {EVAL_HEADLINE.foundRatioMedian.toFixed(3)}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <GenreRanges />
        <BandSeparation />
      </div>
      <Ablation />
    </section>
  );
}
