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
      a real test run, not a scoreboard
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
          <h3 className="font-display font-semibold tracking-tight">{title}</h3>
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
      title="It works across every genre"
      blurb="How close the top matches sound, broken out by genre. Jazz clusters tightest, electronic spreads widest, but every genre lands solidly in range. So it isn't only good at one kind of music."
    >
      <div className="flex flex-col gap-2.5">
        {GENRE_BANDS.map((g) => (
          <div
            key={g.genre}
            className="flex flex-col gap-1.5 sm:grid sm:grid-cols-[5.5rem_1fr_auto] sm:items-center sm:gap-x-3"
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
        scale: 0.30 to 1.00, the range real music falls in
      </p>
    </PanelShell>
  );
}

/** Panel 2: the two legs' bands on one axis — visibly disjoint, so fusion must normalize first. */
function BandSeparation() {
  const legs = [
    { label: "How alike they sound", band: AUDIO_BAND, cls: "bg-audio", note: "the main signal" },
    { label: "Mood match", band: VIBE_BAND, cls: "bg-audio-deep", note: "a lighter touch on purpose" },
  ];
  return (
    <PanelShell
      title="Sound and mood live on different scales"
      blurb="Sound scores cluster high, mood scores cluster low, and they barely overlap. That's exactly why the two get put on the same scale before they're blended. You can't fairly add up numbers that mean different things."
    >
      <div className="flex flex-col gap-4">
        {legs.map((l) => (
          <div
            key={l.label}
            className="flex flex-col gap-1.5 sm:grid sm:grid-cols-[7rem_1fr_auto] sm:items-center sm:gap-x-3"
          >
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
        Same 0.30 to 1.00 scale. The gap between the bars is the whole reason for putting them on one
        scale first.
      </p>
    </PanelShell>
  );
}

/** Panel 3: the ablation — how far CLAP moves the cultural order, with real reranked top-3s. */
function Ablation() {
  return (
    <PanelShell
      title="Listening really changes the order"
      blurb={`Line up the crowd's order against the order after listening (top ${ABLATION.k}): they share only about ${Math.round(ABLATION.overlapMedian * ABLATION.k)} of the ${ABLATION.k} (between ${Math.round(ABLATION.overlapMin * ABLATION.k)} and ${Math.round(ABLATION.overlapMax * ABLATION.k)}), and the typical song moves about ${ABLATION.displacementMedian.toFixed(1)} places (up to ${ABLATION.displacementMax.toFixed(1)}). The listening is doing real work, not just rubber-stamping the crowd.`}
    >
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="bg-muted/40 flex-1 rounded-lg border p-3">
          <div className="text-audio font-mono text-2xl font-semibold tabular-nums">
            ~{Math.round(ABLATION.overlapMedian * ABLATION.k)}
          </div>
          <div className="text-muted-foreground text-xs">
            of the top {ABLATION.k} stay, after listening
          </div>
        </div>
        <div className="bg-muted/40 flex-1 rounded-lg border p-3">
          <div className="text-audio font-mono text-2xl font-semibold tabular-nums">
            {ABLATION.displacementMedian.toFixed(1)}
          </div>
          <div className="text-muted-foreground text-xs">
            places the typical song moves
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        {ABLATION_EXAMPLES.map((ex) => {
          const [title, artist] = ex.seed.split(" by ");
          return (
            <div key={ex.seed} className="border-border/60 rounded-lg border p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <span className="text-sm font-medium">
                  {title}
                  <span className="text-muted-foreground font-normal"> · {artist}</span>
                </span>
                <span className="text-muted-foreground font-mono text-[11px] tabular-nums">
                  kept {Math.round(ex.overlap * ABLATION.k)}/{ABLATION.k} · moved {ex.displacement}
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
        <h2 className="font-display text-2xl font-semibold tracking-tight">Does the listening actually help?</h2>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          These charts come straight from one real test run
          (<span className="font-mono text-xs">{EVAL_PROVENANCE.run}</span>) over every one of the{" "}
          {EVAL_HEADLINE.seedsTotal} benchmark songs. It&rsquo;s a check on what the engine does, not a
          scoreboard. There&rsquo;s no official &ldquo;right answer&rdquo; to grade against, so nothing here
          claims to beat anyone. It just shows the behavior.
        </p>
        <div className="bg-card/50 mt-4 inline-flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border px-4 py-2 font-mono text-sm">
          <span className="font-semibold tabular-nums">
            {EVAL_HEADLINE.seedsAudioScored}/{EVAL_HEADLINE.seedsTotal}
          </span>
          <span className="text-muted-foreground">
            songs scored by sound, across {EVAL_HEADLINE.genres} genres
          </span>
          <span className="text-muted-foreground/50">·</span>
          <span className="text-muted-foreground">typically found this share</span>
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
