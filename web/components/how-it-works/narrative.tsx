/**
 * The design narrative for /how-it-works: the two killed designs, the wedge, the lazy-embedding
 * insight; the competitive positioning (with the honest "where it doesn't win" beat); the
 * design-decision-vs-rejected-alternative cards; and the named deferred items.
 *
 * All prose is product/engineering-framed and neutral — it describes the system and the tradeoffs,
 * never the author or an audience. Every figure traces to CLAUDE.md / the eval run.
 */

/* ── The arc ─────────────────────────────────────────────────────────────────────────────────── */

interface Pivot {
  tag: string;
  title: string;
  body: React.ReactNode;
}

const PIVOTS: Pivot[] = [
  {
    tag: "Dead end 1",
    title: "Let an LLM read the audio",
    body: (
      <>
        The first design had an LLM analyse BPM, key, and Spotify audio features. Two problems killed it:
        Spotify closed those audio endpoints to new apps in 2024, and more fundamentally, asking a language
        model to judge instrumentation asks it to do something it can&rsquo;t — it has never{" "}
        <em>heard</em> the song. That&rsquo;s the seed of the rule that survived to today:{" "}
        <strong>the LLM explains, it never ranks.</strong>
      </>
    ),
  },
  {
    tag: "Dead end 2",
    title: "Pre-embed a royalty-free corpus",
    body: (
      <>
        The next design pre-embedded a free-to-use catalogue (FMA/Jamendo) and matched against it. It was
        algorithmically sound and a product failure: ask for something like a chart hit and you get thirty
        tracks by artists nobody has heard of. It satisfied the math and failed the user.
      </>
    ),
  },
  {
    tag: "The wedge",
    title: "Hybrid retrieve-then-rerank",
    body: (
      <>
        The answer was to make two weak signals cover each other. Cultural sources (Last.fm, ListenBrainz)
        give cheap recall — what listeners <em>treat</em> as similar — and a CLAP audio model reranks for
        what actually <em>sounds</em> similar. Cultural recall keeps the results recognisable; the audio
        rerank keeps them perceptually honest. Neither leg is trustworthy alone.
      </>
    ),
  },
  {
    tag: "What makes it shippable",
    title: "Lazy, self-growing corpus",
    body: (
      <>
        Rather than a weeks-long ETL, the engine embeds only the candidates a query actually surfaces
        (capped at 75) and caches the vectors in pgvector, so the corpus grows itself. That single
        cache-first decision is what lets a warm ~12s request and a cold ~12min one run on the exact same
        code path — the difference is just the cache-miss count.
      </>
    ),
  },
];

function Arc() {
  return (
    <section className="flex flex-col gap-5">
      <div className="max-w-2xl">
        <h2 className="text-2xl font-semibold tracking-tight">Two designs died first</h2>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          The architecture is the residue of killing two reasonable-looking approaches — one that broke on
          external reality, one that broke on real users — and keeping what each failure taught.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {PIVOTS.map((p) => (
          <div key={p.title} className="rounded-xl border p-5">
            <span className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
              {p.tag}
            </span>
            <h3 className="mt-1 font-semibold tracking-tight">{p.title}</h3>
            <p className="text-muted-foreground mt-2 text-sm leading-relaxed">{p.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ── Competitive wedge + honest positioning ──────────────────────────────────────────────────── */

const COMPETITORS = [
  { name: "Spotify / Apple", what: "collaborative filtering — drifts toward what's already popular" },
  { name: "Last.fm", what: "taste-based neighbours, but no audio signal at all" },
  { name: "Chosic / Spotalike", what: "thin wrappers over the Spotify graph" },
  { name: "Maroofy", what: "audio ML, but opaque — no rationale, no controllable steering" },
];

function Wedge() {
  return (
    <section className="flex flex-col gap-5">
      <div className="max-w-2xl">
        <h2 className="text-2xl font-semibold tracking-tight">The four-way combination</h2>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          The wedge is doing four things at once that no single tool does together: cultural recall,
          perceptual audio scoring, controllable text vibe-steering, and a grounded rationale.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {COMPETITORS.map((c) => (
          <div key={c.name} className="border-border/60 flex flex-col gap-1 rounded-lg border p-4">
            <span className="text-sm font-semibold">{c.name}</span>
            <span className="text-muted-foreground text-sm">{c.what}</span>
          </div>
        ))}
      </div>

      <div className="border-audio/40 bg-audio/5 rounded-lg border-l-2 px-4 py-3">
        <p className="text-sm leading-relaxed">
          <strong>Where it doesn&rsquo;t win:</strong> Doppel won&rsquo;t beat Spotify for casual &ldquo;play
          me something similar.&rdquo; The wedge is deliberate discovery — &ldquo;I love this specific song,
          what makes it feel this way, and what else shares that exact quality.&rdquo; Naming where a system
          loses is part of describing what it&rsquo;s for.
        </p>
      </div>
    </section>
  );
}

/* ── Design-decision cards ───────────────────────────────────────────────────────────────────── */

interface Decision {
  chose: string;
  over: string;
  why: React.ReactNode;
}

const DECISIONS: Decision[] = [
  {
    chose: "RRF rank-fusion",
    over: "raw-score fusion",
    why: <>Last.fm&rsquo;s 0–1 match and ListenBrainz&rsquo;s integer score are uncalibrated, so fuse on rank alone — 1/(k+rank), k=60.</>,
  },
  {
    chose: "Learned CLAP embeddings",
    over: "hand-crafted DSP features",
    why: <>Two songs at identical BPM and key can feel nothing alike (deep house vs garage rock). A learned embedding captures texture a feature vector misses.</>,
  },
  {
    chose: "Recording-level canonicalization",
    over: "work-level",
    why: <>Collapsing a live or acoustic take into the studio master surfaces matches the user didn&rsquo;t mean. Only a same-master re-release is suppressed (audio ≥ 0.98 ∧ title token-set ≥ 0.90).</>,
  },
  {
    chose: "Dual-key dedupe",
    over: "MBID alone",
    why: <>Verified MBID <em>and</em> the Deezer track id — because the same recording showed up twice under one Deezer id with different MBIDs.</>,
  },
  {
    chose: "Count-based gates",
    over: "a work-budget estimator",
    why: <>The cold/warm split is gated on the uncached-candidate count, deferring a fancier latency estimator until real query-log calibration data exists.</>,
  },
  {
    chose: "pgvector",
    over: "a dedicated vector DB",
    why: <>Postgres already holds the metadata, logs, and cache, so the vectors live there too — one datastore, no extra operational surface.</>,
  },
];

function Decisions() {
  return (
    <section className="flex flex-col gap-5">
      <div className="max-w-2xl">
        <h2 className="text-2xl font-semibold tracking-tight">Decisions, with the road not taken</h2>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          Each of these is a fork where the rejected option was reasonable — the note is why the other branch
          won.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {DECISIONS.map((d) => (
          <div key={d.chose} className="flex flex-col gap-2 rounded-xl border p-4">
            <div className="flex flex-col gap-0.5">
              <span className="text-audio text-sm font-semibold">{d.chose}</span>
              <span className="text-muted-foreground text-xs">
                over <span className="line-through">{d.over}</span>
              </span>
            </div>
            <p className="text-muted-foreground text-sm leading-relaxed">{d.why}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ── Named deferred items ────────────────────────────────────────────────────────────────────── */

const DEFERRED: { item: string; note: string }[] = [
  { item: "Non-enumerable poll handles", note: "the live job handle is a sequential rec-<int>; opaque tokens are a known follow-up" },
  { item: "API auth + inbound rate limiting", note: "there is no public endpoint today, so neither is built — they're scoped, not shipped" },
  { item: "asyncpg connection-scoping", note: "needed for real request concurrency; the single-worker path doesn't yet" },
  { item: "Cultural-only seed-equivalence", note: "same-artist neighbours (DNA. under HUMBLE.) can still appear — legitimately same-vibe by the recording-level design" },
];

function Deferred() {
  return (
    <section className="flex flex-col gap-5">
      <div className="max-w-2xl">
        <h2 className="text-2xl font-semibold tracking-tight">What&rsquo;s deferred, named not hidden</h2>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          Most of these fall out of the static-showcase architecture: with no public live backend, a whole
          class of hardening is scoped as deliberate judgment rather than built. Listing where the system
          isn&rsquo;t finished is part of describing it honestly.
        </p>
      </div>
      <ul className="flex flex-col gap-3">
        {DEFERRED.map((d) => (
          <li key={d.item} className="border-border/60 flex flex-col gap-0.5 rounded-lg border p-4">
            <span className="text-sm font-semibold">{d.item}</span>
            <span className="text-muted-foreground text-sm">{d.note}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Narrative() {
  return (
    <>
      <Arc />
      <Wedge />
      <Decisions />
      <Deferred />
    </>
  );
}
