/**
 * The curated changelog: the single source of truth for the /changelog page.
 *
 * Hand-authored on purpose (not generated from git): every entry is written in the site's plain,
 * human voice, dated with its real ship date, and linked to the real merged pull request(s) behind
 * it, so a reader can open the actual code. This is the project's whole story (engine + site), newest
 * first. Each `track` ("engine" | "site" | "infra") is a small neutral orientation label, not a
 * colored stream; the retrieval-leg tokens (--cultural/--audio) keep meaning the crowd/the sound
 * everywhere.
 *
 * `highlights` are a scannable mono line of the concrete stack and key metrics per milestone, the
 * engineering substance a technical reader looks for. Keep them to neutral technical facts.
 *
 * MAINTENANCE: when a milestone ships, add an entry at the TOP with its real merge date + PR numbers.
 * The top "This changelog" entry is the page describing itself, not a versioned release, so it stays
 * `caption: "latest version"` with no PR link.
 */

export type ReleaseTrack = "engine" | "site" | "infra";

export interface Release {
  /** Stable slug (anchor / React key). */
  id: string;
  /** Real ship date (the last merge in the release), as ISO yyyy-mm-dd. Drives display + ordering. */
  date: string;
  /** Milestone tag shown after the track, e.g. "v1.2". Optional. */
  version?: string;
  /** Orientation label; omitted for the genesis (the project's "why", which predates any track). */
  track?: ReleaseTrack;
  title: string;
  /** One or two plain sentences. Em-dash-free authored copy. */
  summary: string;
  /** Real merged PR numbers in this release. Empty = not yet merged, or the genesis (no PR). */
  prs: number[];
  /** Caption shown in the PR slot when there are no PRs (e.g. "latest version", "the idea"). */
  caption?: string;
  /** Concrete stack + metrics, rendered as a mono " · "-joined line. NEUTRAL FACTS ONLY (invariant #6). */
  highlights?: string[];
}

export const REPO_URL = "https://github.com/erick-ti/doppel";

export const prUrl = (n: number): string => `${REPO_URL}/pull/${n}`;

export const RELEASES: readonly Release[] = [
  {
    id: "changelog",
    date: "2026-06-19",
    track: "site",
    title: "This changelog",
    summary:
      "A page tracing how Doppel came together, release by release. Each entry links to the real pull request behind it, so you can read the code that shipped it.",
    prs: [],
    caption: "latest version",
  },
  {
    id: "plain-language",
    date: "2026-06-17",
    track: "site",
    title: "Plainer words and polish",
    summary:
      "Rewrote every word on the site to be plain, added hover definitions for the few terms worth keeping, and did an accessibility, mobile, and speed pass.",
    prs: [35],
    highlights: [
      "plain-language rewrite",
      "WCAG accessibility pass",
      "responsive to 320px",
      "perf: memoization + reduced-motion",
    ],
  },
  {
    id: "signal-convergence",
    date: "2026-06-15",
    version: "v1.3",
    track: "site",
    title: "A new look: signal convergence",
    summary:
      "A ground-up redesign around one idea: the crowd and the sound braid into a single result. New type, a warm-charcoal palette, and the seam motif where the two streams meet.",
    prs: [34],
    highlights: [
      "authored design system",
      "type + palette + token register",
      "data-derived fingerprints",
      "Framer Motion",
    ],
  },
  {
    id: "coexistence",
    date: "2026-06-14",
    track: "infra",
    title: "Server hardening for a co-tenant",
    summary:
      "Prepped the server to safely host a second app alongside Doppel, without changing how Doppel stays private and locked down.",
    prs: [33],
    highlights: [
      "multi-tenant VPS prep",
      "OOM protection (oom_score_adj)",
      "fail-closed backup retention",
    ],
  },
  {
    id: "replay-console",
    date: "2026-06-14",
    version: "v1.2",
    track: "site",
    title: "The engine replay console",
    summary:
      "The landing page became an engine console: pick a song and watch a saved run of the real pipeline play back stage by stage, next to a live panel of the production system.",
    prs: [28, 29, 30, 31, 32],
    highlights: [
      "recorded-run replay (RAF clock)",
      "live ops telemetry to Cloudflare R2",
      "healthchecks.io status",
      "host vitals",
      "fail-soft",
    ],
  },
  {
    id: "mood-steering",
    date: "2026-06-12",
    version: "v2",
    track: "engine",
    title: "Mood steering",
    summary:
      "Added a mood lane: type a mood and the engine searches the whole library for songs that fit it, reaching good picks the crowd around your song would never surface. One idea that did not pan out, rewriting a mood into acoustic terms first, was measured and shelved.",
    prs: [24, 25, 26, 27],
    highlights: [
      "HNSW vector search (pgvector)",
      "2×2 A/B test",
      "MBID-native lane redesign",
      "vibe-translation A/B (disproven, shelved)",
    ],
  },
  {
    id: "showcase-site",
    date: "2026-05-31",
    version: "v1.1",
    track: "site",
    title: "The showcase site",
    summary:
      "The first version of this site. Doppel's engine stays private, so the site serves frozen results from real runs of curated songs, with a gallery, an honest score breakdown, and a how-it-works layer.",
    prs: [16, 17, 18, 19, 20, 21, 22, 23],
    highlights: [
      "Next.js static export",
      "real frozen pipeline output",
      "Tailwind",
      "responsive + a11y",
      "Vercel",
    ],
  },
  {
    id: "v1-live",
    date: "2026-05-28",
    version: "v1",
    track: "engine",
    title: "Live, and measured",
    summary:
      "Doppel went live on a small server, then got put to the test. A run across a benchmark of songs from many genres confirmed it held up, tuned the dials, and caught a bug where a song could recommend a different recording of itself. Daily backups, an off-site copy, and failure alerts rounded it out.",
    prs: [7, 8, 9, 10, 11, 12, 13, 14, 15],
    highlights: [
      "Docker on a Hetzner VPS",
      "loopback + SSH-only",
      "image 10.6 GB → 2.2 GB",
      "encrypted off-site backups",
      "19-seed eval benchmark",
      "cold 701s → warm 12s",
    ],
  },
  {
    id: "v1-core",
    date: "2026-05-24",
    track: "engine",
    title: "The core engine",
    summary:
      "The heart of it, built over a few days: gather candidate songs from what listeners connect to your pick, match and de-duplicate them, listen to each preview and turn the sound into numbers, score those against your song, and ask an LLM to write the short note for each pick (it explains, it never ranks). All behind one API.",
    prs: [2, 3, 4, 5, 6],
    highlights: [
      "Python",
      "async (httpx/asyncio)",
      "CLAP embeddings (PyAV decode)",
      "Postgres + pgvector",
      "ARQ + Redis worker",
      "two-gate async pipeline",
      "FastAPI + Claude (prompt-cached)",
    ],
  },
  {
    id: "v1-day0",
    date: "2026-05-21",
    version: "day 0",
    track: "engine",
    title: "Proving it could work",
    summary:
      "Before writing the engine, every outside piece it would lean on got a feasibility check: the music data sources, Deezer's song previews, and the CLAP model that does the listening. They held up, so the build got a green light.",
    prs: [1],
    highlights: [
      "feasibility probe",
      "Last.fm / ListenBrainz / MusicBrainz / Deezer",
      "CLAP load + embed",
      "GO verdict",
    ],
  },
  {
    id: "genesis",
    date: "2026-05-19",
    title: "Why Doppel exists",
    summary:
      "Spotify shut off the recommendations API that a generation of music apps were built on. Doppel started from a simple question: could you match the feeling of a song, its mood and texture, by blending what listeners connect it to with how it actually sounds? That question is the whole engine.",
    prs: [],
    caption: "the idea",
  },
] as const;
