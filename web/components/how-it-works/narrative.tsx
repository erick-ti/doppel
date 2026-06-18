/**
 * The design narrative for /how-it-works: the two killed designs, the wedge, the lazy-embedding
 * insight; the competitive positioning (with the honest "where it doesn't win" beat); the
 * design-decision-vs-rejected-alternative cards; and the named deferred items.
 *
 * All prose is product/engineering-framed and neutral — it describes the system and the tradeoffs,
 * never the author or an audience. Every figure traces to CLAUDE.md / the eval run.
 */

import { Term } from "@/components/term";

/* ── The arc ─────────────────────────────────────────────────────────────────────────────────── */

interface Pivot {
  tag: string;
  title: string;
  body: React.ReactNode;
}

const PIVOTS: Pivot[] = [
  {
    tag: "First try",
    title: "Ask an AI to read the audio",
    body: (
      <>
        The first version had an AI look at a song&rsquo;s tempo and key from Spotify&rsquo;s data. Two
        things killed it. Spotify shut those numbers off to new apps in 2024, and more to the point, asking
        an AI to judge how a song sounds asks it to do something it can&rsquo;t: it has never actually{" "}
        <em>heard</em> the song. That&rsquo;s where today&rsquo;s rule came from:{" "}
        <strong>the AI explains the picks, it never chooses them.</strong>
      </>
    ),
  },
  {
    tag: "Second try",
    title: "Build from a free music library",
    body: (
      <>
        The next version listened to a library of free-to-use songs ahead of time and matched against that.
        The math worked and the product didn&rsquo;t: ask for something like a chart hit and you get thirty
        songs by artists you&rsquo;ve never heard of. It was right and useless.
      </>
    ),
  },
  {
    tag: "What stuck",
    title: "Use the crowd and the sound",
    body: (
      <>
        The fix was to let two so-so signals cover for each other. The crowd (from Last.fm and ListenBrainz)
        cheaply suggests songs people treat as similar, and{" "}
        <Term name="clap">a model that listens</Term> re-sorts them by what actually sounds alike. The crowd
        keeps the picks recognizable. The listening keeps them honest. Neither is good enough on its own.
      </>
    ),
  },
  {
    tag: "Why it’s practical",
    title: "It remembers what it hears",
    body: (
      <>
        Instead of listening to a giant library up front, it only listens to the songs a search actually
        turns up (at most 75), and <Term name="embedding">saves what it hears</Term>. So its memory grows on
        its own. That one choice is why the same code answers a familiar song in about 12 seconds and a
        brand-new one in about 12 minutes: the only difference is how much it already knew.
      </>
    ),
  },
];

/** Per-pivot accent: the dead ends fade, the surviving "wedge" carries the --seam rail, the
 *  shippability pivot the cool audio rail — so the arc reads as designs dying into the one that won. */
function pivotAccent(tag: string): { rail: string; faded: boolean } {
  if (tag === "First try" || tag === "Second try") return { rail: "border-l-border", faded: true };
  if (tag === "What stuck") return { rail: "border-l-seam", faded: false };
  return { rail: "border-l-audio", faded: false };
}

function Arc() {
  return (
    <section className="flex flex-col gap-5">
      <div className="max-w-2xl">
        <h2 className="font-display text-2xl font-semibold tracking-tight">Two designs died first</h2>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          Doppel is what&rsquo;s left after two reasonable-looking ideas didn&rsquo;t pan out. One broke on
          the outside world, one broke on real people. It kept what each of them taught.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {PIVOTS.map((p) => {
          const a = pivotAccent(p.tag);
          return (
            <div
              key={p.title}
              className={`rounded-xl border border-l-[3px] p-5 ${a.rail} ${a.faded ? "opacity-70" : ""}`}
            >
              <span className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
                {p.tag}
              </span>
              <h3 className="font-display mt-1 font-semibold tracking-tight">{p.title}</h3>
              <p className="text-muted-foreground mt-2 text-sm leading-relaxed">{p.body}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/* ── Competitive wedge + honest positioning ──────────────────────────────────────────────────── */

const COMPETITORS = [
  { name: "Spotify / Apple", what: "go by what's already popular" },
  { name: "Last.fm", what: "know your taste, but never listen to the song" },
  { name: "Chosic / Spotalike", what: "thin wrappers over Spotify's data" },
  { name: "Maroofy", what: "listen, but it's a black box: no reasons, no controls" },
];

function Wedge() {
  return (
    <section className="flex flex-col gap-5">
      <div className="max-w-2xl">
        <h2 className="font-display text-2xl font-semibold tracking-tight">What makes it different</h2>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          It does four things at once that no single tool does together: lean on the crowd, judge the
          actual sound, let you nudge by mood, and explain each pick in plain words.
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
          <strong>Where it doesn&rsquo;t win:</strong> Doppel won&rsquo;t beat Spotify for a casual
          &ldquo;play me something similar.&rdquo; It&rsquo;s built for the deliberate kind of digging:
          &ldquo;I love this exact song, what gives it that feel, and what else has it.&rdquo; Saying where
          it loses is part of saying what it&rsquo;s for.
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
    chose: "Combine by rank",
    over: "combine raw scores",
    why: <>Last.fm&rsquo;s and ListenBrainz&rsquo;s scores aren&rsquo;t on the same scale, so it combines them by rank position instead of raw numbers.</>,
  },
  {
    chose: "A model that listens",
    over: "hand-coded audio measurements",
    why: <>Two songs at the same tempo and key can feel nothing alike (deep house vs garage rock). A model that learned from real audio catches texture that simple measurements miss.</>,
  },
  {
    chose: "Match the exact recording",
    over: "match the song in general",
    why: <>Folding a live or acoustic take into the studio version turns up matches you didn&rsquo;t mean. Only a true re-release of the same recording gets filtered out.</>,
  },
  {
    chose: "Check two IDs",
    over: "trust one ID",
    why: <>It checks both IDs, because the same recording once showed up twice under one Deezer id with two different MusicBrainz ids.</>,
  },
  {
    chose: "Count, don’t guess",
    over: "estimate the time up front",
    why: <>It picks the fast path or slow path by simply counting how many songs it hasn&rsquo;t heard yet, rather than trying to guess how long the run will take.</>,
  },
  {
    chose: "Keep it in Postgres",
    over: "add a separate vector database",
    why: <>Postgres already holds the data and the logs, so the audio fingerprints live there too. One database, nothing extra to run.</>,
  },
];

function Decisions() {
  return (
    <section className="flex flex-col gap-5">
      <div className="max-w-2xl">
        <h2 className="font-display text-2xl font-semibold tracking-tight">The calls behind it</h2>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          Each of these was a real fork in the road, where the option not taken was perfectly reasonable.
          The note says why the other one won. This part is the engineering, if you want it.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {DECISIONS.map((d) => (
          <div key={d.chose} className="border-l-seam/40 flex flex-col gap-2 rounded-xl border border-l-2 p-4">
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
  { item: "Harder-to-guess job links", note: "the live job link is a simple counter today; making it unguessable is a known to-do" },
  { item: "Login and rate limits on the API", note: "there's no public endpoint yet, so neither is built. Planned, not done." },
  { item: "Per-request database connections", note: "needed once many people hit it at once; the single-worker setup doesn't need it yet" },
  { item: "Same-artist near-matches", note: "a track by the same artist can still show up. By design, that's a fair match." },
];

function Deferred() {
  return (
    <section className="flex flex-col gap-5">
      <div className="max-w-2xl">
        <h2 className="font-display text-2xl font-semibold tracking-tight">What&rsquo;s not built yet</h2>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          Most of these come from the same choice to keep this a saved, no-live-backend showcase: a whole
          batch of hardening is planned on purpose rather than built. Listing what isn&rsquo;t finished is
          part of being straight about it.
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
