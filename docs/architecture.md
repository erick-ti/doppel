# Architecture

Doppel matches the *vibe* of a seed song (its mood, texture, and production
feel) by combining two signals that fail in different places:

- **Cultural retrieval** knows what humans think is similar. Last.fm and
  ListenBrainz surface tracks that listeners connect to the seed, including
  scene adjacency that pure audio analysis misses.
- **Audio embedding** knows what actually sounds similar. A CLAP model turns
  each candidate's preview into a 512-dimensional vector and scores it against
  the seed, catching sonic matches that taste-based systems miss.

The engine is a hybrid **retrieve-then-rerank** pipeline: cultural sources
generate candidates, audio embeddings rerank them, and an LLM explains the
result. The LLM never ranks; ranking belongs to the audio and cultural scores.

## The pipeline

```
seed (title, artist, optional mood text)
        │
        ▼
   aggregate ── Last.fm + ListenBrainz, conservative dedupe, RRF (k=60)
        │        → cultural candidate pool
        ▼
   ┌─ Gate 1 (WARM / COLD) ── uncached-lookup count
   │                          COLD → enqueue a job, return a poll handle
        │
        ▼
   resolve ──── each candidate → MusicBrainz canonical MBID + Deezer preview,
        │        verified by the matcher; cached in canonical_lookups / audio_assets
        ▼
   ┌─ Gate 2 (WARM / COLD) ── missing-embedding count
   │
        ▼
   embed ────── stream the preview into memory, decode with PyAV, CLAP →
        │        a 512-dim vector, discard the audio; cached in embeddings
        ▼
   fuse ─────── cosine(seed audio, candidate audio) + optional cosine(mood, candidate),
        │        each min-max normalized within the batch, combined α·audio + β·mood
        ▼
   backfill ─── if fewer than 10 audio-scored results, fill from cultural RRF order
        │
        ▼
   explain ──── one batched Claude call writes a short rationale per result
        │        (explanation only, degradable to no rationales)
        ▼
   results  ─── persisted to query_logs + query_log_results
```

### Stages

1. **aggregate** turns a seed `(title, artist)` into a ranked cultural pool.
   Last.fm `track.getSimilar` and ListenBrainz Labs `similar-recordings` are
   queried concurrently, each isolated so one failing source degrades rather
   than sinks the run. Results are conservatively deduplicated (only formatting
   noise is folded; variant tokens like "live", "acoustic", and "remix" are
   kept, because two versions of a song can feel completely different) and
   ranked by Reciprocal Rank Fusion. RRF is rank-based, so it needs no
   calibration between Last.fm's and ListenBrainz's incomparable native scores,
   and it naturally boosts tracks both sources agree on.

2. **resolve** canonicalizes each candidate's messy `(title, artist)` string
   into a recording-level MusicBrainz MBID and fetches a Deezer preview for it.
   The matcher verifies the preview is the same recording (not a cover, live
   take, or remix) from three signals: an ISRC match (instant confidence), a
   duration delta against the full track length, and RapidFuzz title/artist
   similarity. Resolutions and previews are cached, so MusicBrainz's rate limit
   and Deezer are not re-hit for a track already seen.

3. **embed** streams each verified preview into memory, decodes it with PyAV,
   and runs CLAP to produce a 512-dimensional vector. The audio is never
   written to disk. Embedding is deterministic: the clip is sliced into windows
   of at most 10 seconds and the window vectors are duration-weighted and
   pooled, because CLAP's feature extractor otherwise crops audio randomly and
   would poison a cached vector. Vectors are stored in pgvector, keyed by
   `(mbid, model_version)`.

4. **fuse** reranks the candidates. Each candidate's audio cosine against the
   seed (and, when a mood is given, its cosine against the mood text) is
   min-max normalized within the batch, then combined as `α·audio + β·mood`
   (0.7 / 0.3 by default). Normalizing within the batch matters because audio
   cosine scale is genre-dependent, so a fixed cross-genre threshold would be
   wrong. A second retrieval lane (added in v2) runs only when a mood is given:
   it searches the whole embedding corpus by the mood vector (an HNSW
   nearest-neighbor query) to surface on-mood tracks the seed's cultural pool
   could not contain.

5. **backfill** fills any shortfall. If fewer than 10 candidates were
   audio-scored (a thin or degraded run), the top of the cultural RRF ordering
   completes the list, so a partial audio signal still returns a full,
   honestly-labeled result set.

6. **explain** makes one batched call to Claude that writes a concise rationale
   per result, keyed by position and grounded only in the metadata and scores
   in the prompt. It is explanation only, never ranking, and fully degradable:
   no API key, an error, or a timeout returns results without rationales rather
   than failing the request.

## The two-gate WARM / COLD design

MusicBrainz allows roughly one request per second, so resolving a fresh seed's
uncached candidates (capped at the top 75 to bound cold latency) can take
minutes, while a seed whose candidates are already cached answers in seconds
rather than minutes. The pipeline splits these two
cases with two gates. **Gate 1**, in the API, counts the *uncached* canonical
lookups a request needs; **Gate 2**, inside the pipeline, counts the missing
embeddings. If either count is over its threshold the request is COLD: the API
returns `202` with a poll handle and an ARQ worker runs the pipeline in the
background, its status readable from Postgres. Otherwise the request is WARM and
runs inline to a `200`.

The same `run_pipeline` coroutine serves both modes; the database cache is the
stage boundary. A COLD job re-runs the whole pipeline, and the
`canonical_lookups`, `audio_assets`, and `embeddings` rows the first pass
persisted turn the expensive work into cache hits, so no partial state has to
be serialized across the job queue. Only the seed and the cultural pool cross
it. This design was chosen over separate per-stage jobs (which would need their
own state handoff and retry policies for stages a caller never sees) and over a
synchronous-only API (which cannot absorb MusicBrainz's pacing).

## Persistence

Five tables hold the persisted state the lazy-embedding design needs (four are
the caching corpus; `query_logs` is per-request telemetry):

- `tracks`: MusicBrainz recording identity (MBID, title, artist, duration,
  ISRCs).
- `audio_assets`: provider evidence per track (preview URL, provider duration,
  match confidence, status).
- `embeddings`: 512-dim CLAP vectors, keyed by `(mbid, model_version)`, with an
  HNSW cosine index for the mood-retrieval lane.
- `canonical_lookups`: the resolve cache and negative cache. A normalized
  candidate string maps to an outcome and MBID, and it is what Gate 1 counts.
- `query_logs`: one row per request.

Identity, provider evidence, and vectors are kept in separate tables on purpose.
A track can have several provider assets at different confidences, previews
expire and need retry, and a match confidence describes a specific asset rather
than the track. Mixing these onto one table made it semantically incoherent.

## Observability: telemetry in Postgres, not logs

Doppel deliberately runs without a logging framework. Instead, every request
writes a `query_logs` row and its results write `query_log_results` rows. Those
rows carry the gate outcomes and the counts they were compared against, the
yield and latency, and which candidate sources degraded (the aggregator records
each failed source, and the API surfaces them in a `degraded` block on the
response). Candidate provider failures are captured the same way rather than
logged and forgotten.

This is a choice, not an omission. The telemetry that actually matters here is
calibration data: the gate thresholds against real counts, genre coverage,
score distributions, and audio-versus-cultural ablation. That is trivial to
answer as SQL over a normalized child table and painful to reconstruct from
scattered log lines. The evaluation harness reads exactly these rows to tune the
engine's knobs. A logging framework can be added later without disturbing this;
the queryable telemetry is the load-bearing part.
