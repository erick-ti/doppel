"""v2 Phase 1 — HNSW hybrid measurement (THROWAWAY eval, gates the lane build, NOT production).

The feasibility spike proved global knn(vibe) RETRIEVES plausible on-vibe tracks. The open crux it
did NOT test: the pipeline reranks by audio-similarity-to-the-SEED, so for a steer-away vibe (HUMBLE.
→ acoustic) the retrieved acoustic tracks have LOW audio-sim-to-seed — does the score_candidates
fusion (with the unlocked β≈0.5, min-max-normalized vibe leg) let them SURVIVE into the top-10, or
does the audio leg bury them? If they survive, the lane is worth building; if they're buried, the
build also needs a scoring change (DECISIONS.md).

Method, per vibe seed (corpus is already warm, so no run_pipeline / resolve loop needed):
  1. aggregate() → cultural candidates; reconstruct the embedded subset from the warm cache
     (get_canonical_lookup FOUND → fetch_embeddings), tagged source="cultural".
  2. HNSW lane: embed the vibe → knn(vibe, K) → fetch those vectors, tagged source="hnsw", deduped.
  3. score_candidates(seed_audio, cultural+hnsw, vibe_text=vibe_vec, α=β=0.5) and READ the top-15:
     how many of the top-10 are HNSW-sourced, and are they plausible for the vibe?

Run: DATABASE_URL=postgresql://doppel:doppel@localhost:5433/doppel \
        uv run --group clap python -m eval.hnsw_hybrid
"""
from __future__ import annotations

import asyncio

import numpy as np

from doppel import db
from doppel.aggregation.aggregator import aggregate
from doppel.config import CLAP_MODEL_VERSION
from doppel.embedding.scoring import score_candidates
from doppel.explanation import ClaudeExplainer
from doppel.pipeline.deps import build_deps, close_deps
from doppel.sources.lastfm import LastFmClient
from doppel.sources.listenbrainz import ListenBrainzClient

from eval.seeds import Seed

_CULTURAL_TOP_N = 40   # cap the cultural pool we reconstruct
_HNSW_K = 20           # corpus-wide vibe-retrieved candidates
_ALPHA, _BETA = 0.5, 0.5  # the β-sweep's "steering becomes visible" point

SEEDS = [
    Seed("HUMBLE.", "Kendrick Lamar", "hip-hop", vibe="stripped back, acoustic, intimate"),     # STEER-AWAY
    Seed("Blinding Lights", "The Weeknd", "pop", vibe="slow melancholic acoustic ballad"),       # STEER-AWAY
    Seed("Midnight City", "M83", "electronic", vibe="melancholic, late-night driving"),          # descriptive
    Seed("Take Five", "The Dave Brubeck Quartet", "jazz", vibe="rainy day, contemplative"),      # descriptive
]


async def _titles(conn, mbids) -> dict[str, tuple[str, str]]:
    if not mbids:
        return {}
    rows = await conn.fetch("SELECT mbid, title, artist FROM tracks WHERE mbid = ANY($1::uuid[])", mbids)
    return {str(r["mbid"]): (r["title"], r["artist"]) for r in rows}


async def _seed_mbid(conn, seed: Seed) -> str | None:
    look = await db.get_canonical_lookup(conn, seed.title, seed.artist)
    return str(look["mbid"]) if look and look["status"] == "found" and look["mbid"] else None


async def run_seed(deps, sources, seed: Seed) -> None:
    result = await aggregate(sources, seed.title, seed.artist)
    vibe_vec = await asyncio.to_thread(deps.embedder.embed_text, seed.vibe)

    async with deps.pool.acquire() as conn:
        seed_mbid = await _seed_mbid(conn, seed)
        seed_row = await db.get_embedding(conn, seed_mbid, CLAP_MODEL_VERSION) if seed_mbid else None
        if seed_row is None:
            print(f"── {seed.label}: seed not embedded in corpus — skip\n")
            return

        # cultural embedded subset (warm-cache reconstruction; FOUND lookups only)
        cult_mbids: list[str] = []
        for c in result.candidates[:_CULTURAL_TOP_N]:
            look = await db.get_canonical_lookup(conn, c.title, c.artist)
            if look and look["status"] == "found" and look["mbid"]:
                m = str(look["mbid"])
                if m != seed_mbid:
                    cult_mbids.append(m)
        cult_mbids = list(dict.fromkeys(cult_mbids))
        cult_rows = await db.fetch_embeddings(conn, cult_mbids, CLAP_MODEL_VERSION)
        cult_set = {str(r["mbid"]) for r in cult_rows}

        # HNSW vibe lane: knn ranks by vibe, then bulk-fetch the vectors (knn returns mbid+distance only)
        hits = await db.knn(conn, vibe_vec, _HNSW_K, model_version=CLAP_MODEL_VERSION)
        hnsw_mbids = [str(h["mbid"]) for h in hits if str(h["mbid"]) != seed_mbid and str(h["mbid"]) not in cult_set]
        hnsw_rows = await db.fetch_embeddings(conn, list(dict.fromkeys(hnsw_mbids)), CLAP_MODEL_VERSION)

        titles = await _titles(conn, list(cult_set) + [str(r["mbid"]) for r in hnsw_rows])

    seed_audio = np.asarray(seed_row["embedding"], dtype=np.float64)
    batch: list[tuple[str, str]] = []  # (mbid, source) aligned with `vecs`
    vecs: list[np.ndarray] = []
    for r in cult_rows:
        batch.append((str(r["mbid"]), "cult")); vecs.append(np.asarray(r["embedding"], dtype=np.float64))
    for r in hnsw_rows:
        batch.append((str(r["mbid"]), "HNSW")); vecs.append(np.asarray(r["embedding"], dtype=np.float64))

    if len(vecs) < 2:
        print(f"── {seed.label}: only {len(vecs)} embedded candidates — skip\n")
        return

    scored = score_candidates(seed_audio, vecs, vibe_text=vibe_vec, alpha=_ALPHA, beta=_BETA)
    n_cult = sum(1 for _, s in batch if s == "cult")
    n_hnsw = sum(1 for _, s in batch if s == "HNSW")
    hnsw_in_top10 = sum(1 for sc in scored[:10] if batch[sc.index][1] == "HNSW")

    print(f"── {seed.label}")
    print(f"   pool: {n_cult} cultural + {n_hnsw} hnsw  ·  HNSW in fused top-10: {hnsw_in_top10}/10")
    for r, sc in enumerate(scored[:15], 1):
        m, src = batch[sc.index]
        t, a = titles.get(m, ("(?)", "(?)"))
        print(f"   {r:2}. [{src}] comb={sc.combined_score:.3f} aud={sc.audio_similarity:.3f} "
              f"vibe={sc.text_similarity:.3f}  {t} — {a}")
    print()


async def main() -> None:
    deps = await build_deps(enqueue_job=None)
    if isinstance(deps.explainer, ClaudeExplainer):
        await deps.explainer.aclose()
    deps.explainer = None
    sources = [ListenBrainzClient(deps.http), LastFmClient(deps.http)]
    try:
        async with deps.pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT count(*) FROM servable_embeddings WHERE model_version = $1", CLAP_MODEL_VERSION
            )
        print(f"corpus: {total} servable embeddings · α/β={_ALPHA}/{_BETA} · HNSW K={_HNSW_K}\n")
        for seed in SEEDS:
            try:
                await run_seed(deps, sources, seed)
            except Exception as exc:  # a measurement tool: report and continue
                print(f"── {seed.label}: ERROR {type(exc).__name__}: {exc}\n")
    finally:
        await close_deps(deps)


if __name__ == "__main__":
    asyncio.run(main())
