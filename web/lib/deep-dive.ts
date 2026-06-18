/**
 * Config + script for the /deep-dive route — a written, act-by-act walkthrough of what the live run
 * shows (the data below). The interactive replay console (recorded telemetry) carries the "it really
 * runs" proof; this page is the prose narration of the cold→warm story behind it.
 *
 * Every number is verified against src/doppel/config.py: two async gates (GATE1_ASYNC_THRESHOLD=5
 * uncached lookups → defer resolution; GATE2_ASYNC_THRESHOLD=10 found-but-unembedded → defer
 * embedding), RESOLVE_CANDIDATE_LIMIT=75, WORKER_MAX_JOBS=1, RRF_K=60, AUDIO_SIM_WEIGHT=0.7 /
 * VIBE_TEXT_WEIGHT=0.3, RECOMMENDATION_LIMIT=10. Latency: warm ~12s (the median `latency_ms` across
 * the frozen exports); cold ≈ 701s ≈ ~12 min END-TO-END, measured in prod on 2026-05-27 (DECISIONS.md
 * / ROADMAP.md). The MusicBrainz resolve is the bulk of that — cap-bounded at ~75×7s ≈ 9 min
 * (RESOLVE_CANDIDATE_LIMIT × COLD_RESOLVE_SECONDS_PER_CANDIDATE, matching DEPLOY.md's "~N×7s") — with
 * embedding, scoring, and the rationale on top. Narrated as approximate.
 */

export interface Act {
  n: number;
  title: string;
  /** What the act demonstrates, in plain prose. */
  beats: string[];
}

export const ACTS: readonly Act[] = [
  {
    n: 1,
    title: "It's live",
    beats: [
      "POST /recommend with Take Five by The Dave Brubeck Quartet against a warm corpus returns a 200 in about 12 seconds.",
      "The top neighbours are real: Alphanumeric by Lee Konitz, Red Pepper Blues by Art Pepper, Three to Get Ready by Dave Brubeck.",
      "Note that the seed's own studio master never appears. A near-duplicate of the seed (audio ≥ 0.98 and a title-token match) is suppressed, so the engine never recommends the song back to itself, while a live or acoustic take, which scores lower, survives.",
    ],
  },
  {
    n: 2,
    title: "The cold cliff is real, and it's on purpose",
    beats: [
      "POST a never-seen seed and the API returns 202 JobAccepted with a queued job handle and a status URL, rather than blocking the request. That's Gate 1: at 5 or more uncached candidate lookups (the ones that hit MusicBrainz at ~1 req/s), resolution is deferred to the async worker up front.",
      "The whole cold request took about 701 seconds (~12 minutes) end to end in production. Most of that is the ARQ worker grinding MusicBrainz at roughly one request a second, about 7 seconds per candidate. It's bounded on purpose: RESOLVE_CANDIDATE_LIMIT=75 caps the resolve at ~75×7s ≈ 9 minutes (embedding, scoring, and the rationale make up the rest), and WORKER_MAX_JOBS=1 because cold work is MusicBrainz-bound, so concurrency would buy no throughput, only multiply latency.",
      "Polling the status URL returns 202 while it runs, then flips to 200 with the full recommendation response, degradation block and all. The job handle is a plain sequential id. Non-enumerable tokens and auth are a named, deferred item, not a gap being hidden (it's why there's no public live endpoint).",
      "Re-run the exact same seed and it returns a warm 200 in ~12 seconds, now with a high embeddings-cache-hit count. That's the lazy-corpus payoff: the first run grew the pgvector cache, so the second skips the embedding work entirely.",
    ],
  },
  {
    n: 3,
    title: "Why it's built this way",
    beats: [
      "The pivots: an LLM can't judge audio it never heard (and Spotify closed those endpoints to new apps in 2024), and a pre-embedded royalty-free corpus answers a chart hit with unknown tracks. The hybrid retrieve-then-rerank design is what survived. CLAP owns ranking, the LLM only explains.",
      "Open the eval reports and walk the ablation: at the resolve cap of 75, the CLAP-reranked top-10 shares a median of just 0.2 of its order with the pure cultural ranking, moving tracks a median of 3.4 places. The audio leg is doing real work, not passing the cultural order through.",
      "Open the Postgres query_logs / query_log_results row backing that poll: the durable, dual-persisted telemetry that the static showcase JSON is a serialization of. Same numbers, live source of truth.",
      "Honest closer: Doppel won't beat Spotify for casual 'play me something similar.' The wedge is deliberate discovery, and the deferred hardening (auth, rate limiting, opaque handles, connection-scoping) is scoped engineering judgment, named not hidden.",
    ],
  },
] as const;
