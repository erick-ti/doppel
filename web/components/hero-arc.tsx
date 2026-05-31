/**
 * The "short version" — a compact problem → dead-ends → wedge → evidence arc that frames why Doppel
 * is built as a hybrid retrieve-then-rerank engine. Pure content (server component); the leg accents
 * (amber = cultural recall, blue = audio rerank) match the two-leg duality carried across the app.
 *
 * Copy stays product/engineering-framed and neutral. The numbers it cites are the same real eval
 * figures the proof ribbon and the per-seed funnel show — no claim here that isn't backed elsewhere.
 */

type Accent = "neutral" | "cultural" | "audio" | "both";

const ACCENT_BAR: Record<Accent, string> = {
  neutral: "bg-muted-foreground",
  cultural: "bg-cultural",
  audio: "bg-audio",
  both: "bg-gradient-to-r from-cultural to-audio",
};

interface Beat {
  step: string;
  label: string;
  accent: Accent;
  body: React.ReactNode;
}

const BEATS: Beat[] = [
  {
    step: "01",
    label: "The problem",
    accent: "neutral",
    body: (
      <>
        “Play me something like this” usually resolves to collaborative
        filtering, which drifts toward whatever is already popular — or to taste
        graphs that never actually listen to the song.
      </>
    ),
  },
  {
    step: "02",
    label: "Two dead ends",
    accent: "cultural",
    body: (
      <>
        Asking an LLM to read a track’s BPM and key assumes it has{" "}
        <em>heard</em> the song (it hasn’t), and Spotify closed those audio
        endpoints to new apps in 2024. Pre-embedding a royalty-free corpus
        satisfies the math but answers a chart hit with thirty tracks nobody has
        heard of.
      </>
    ),
  },
  {
    step: "03",
    label: "The wedge",
    accent: "both",
    body: (
      <>
        The fix is to let each leg cover the other’s blind spot: cultural
        sources know what listeners <em>treat</em> as similar, the audio model
        knows what actually <em>sounds</em> similar. Neither is trustworthy
        alone; together they are.
      </>
    ),
  },
  {
    step: "04",
    label: "The evidence",
    accent: "audio",
    body: (
      <>
        19/19 benchmark seeds audio-scored across 8 genres, and the rerank
        visibly reshapes the cultural shortlist — the funnel on every result
        page shows that narrowing on real numbers.
      </>
    ),
  },
];

export function HeroArc() {
  return (
    <section className="border-border/60 border-t py-12 sm:py-16">
      <div className="mb-8 max-w-2xl">
        <h2 className="text-2xl font-semibold tracking-tight">
          The short version
        </h2>
        <p className="text-muted-foreground mt-2 text-sm">
          How a “find songs that sound alike” idea became a two-leg retrieve-then-rerank
          pipeline.
        </p>
      </div>

      <ol className="grid grid-cols-1 gap-x-8 gap-y-8 sm:grid-cols-2">
        {BEATS.map((beat) => (
          <li key={beat.step} className="flex flex-col gap-3">
            <div className="flex items-center gap-3">
              <span className={`h-0.5 w-8 rounded-full ${ACCENT_BAR[beat.accent]}`} aria-hidden />
              <span className="text-muted-foreground font-mono text-xs tabular-nums">
                {beat.step}
              </span>
              <h3 className="text-sm font-semibold tracking-wide">{beat.label}</h3>
            </div>
            <p className="text-muted-foreground max-w-prose leading-relaxed">
              {beat.body}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
