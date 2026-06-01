"""v2 — bounded HNSW feasibility spike (THROWAWAY exploration, NOT a retrieval lane).

The live A/B disconfirmed vibe-translation; the standing question it raised is whether the engine's
weakness is the text *vector* or the candidate *pool*. Steering-away vibes ("HUMBLE. but acoustic")
fail because the seed's cultural pool is all hip-hop — there is nothing acoustic to steer toward. This
probe asks, directly: can global corpus-wide ANN retrieval (knn over the existing HNSW index) surface
human-PLAUSIBLE tracks for a vibe — especially the steer direction the cultural pool lacks — and is the
~1k-row corpus even diverse enough to contain those tracks?

It is a go/no-go signal, judged by READING the retrieved titles, not by scores. If global retrieval
returns plausible on-vibe tracks (esp. for the steer-away queries), HNSW earns a real v2 design pass.
If it returns the corpus's nearest-but-still-wrong tracks (because the corpus has nothing on-vibe),
the bottleneck is corpus density, and HNSW can't help without densification (deferred).

Run: DATABASE_URL=postgresql://doppel:doppel@localhost:5433/doppel \
        uv run --group clap python -m eval.hnsw_spike
"""
from __future__ import annotations

import asyncio

from doppel import db
from doppel.config import CLAP_MODEL_VERSION
from doppel.pipeline.deps import build_deps, close_deps

# A mix of STEER-AWAY vibes (the real test — the vibe asks for the opposite of the genre heroes whose
# pools dominate the corpus) and DESCRIPTIVE vibes (the vibe ≈ a sound the corpus should contain).
QUERIES: list[tuple[str, str]] = [
    ("sparse acoustic guitar, intimate, stripped back, unplugged", "STEER-AWAY (vs the hip-hop pool — HUMBLE.)"),
    ("slow melancholic acoustic ballad, soft piano, quiet", "STEER-AWAY (vs upbeat synth-pop — Blinding Lights)"),
    ("calm, gentle, ambient, peaceful, meditative", "STEER-AWAY (vs pop-punk — good 4 u)"),
    ("aggressive, fast, distorted electric guitars, heavy", "STEER-AWAY (vs mellow jazz — Take Five)"),
    ("melancholic late-night driving, dreamy reverb-drenched synth", "DESCRIPTIVE (M83-like)"),
    ("smooth warm soul, groovy r&b, mellow", "DESCRIPTIVE (r&b — should exist in pool)"),
    ("upbeat danceable electronic, four-on-the-floor, energetic", "DESCRIPTIVE (electronic — should exist)"),
    ("contemplative jazz, brushed drums, soft piano, rainy day", "DESCRIPTIVE (jazz — should exist)"),
]


async def _titles(conn, mbids) -> dict[str, tuple[str, str]]:
    if not mbids:
        return {}
    rows = await conn.fetch(
        "SELECT mbid, title, artist FROM tracks WHERE mbid = ANY($1::uuid[])", mbids
    )
    return {str(r["mbid"]): (r["title"], r["artist"]) for r in rows}


async def main() -> None:
    deps = await build_deps(enqueue_job=None)
    try:
        async with deps.pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT count(*) FROM servable_embeddings WHERE model_version = $1", CLAP_MODEL_VERSION
            )
        print(f"corpus: {total} servable embeddings @ {CLAP_MODEL_VERSION}\n")
        for vibe, label in QUERIES:
            vec = await asyncio.to_thread(deps.embedder.embed_text, vibe)
            async with deps.pool.acquire() as conn:
                hits = await db.knn(conn, vec, 10, model_version=CLAP_MODEL_VERSION)
                titles = await _titles(conn, [h["mbid"] for h in hits])
            print(f'── "{vibe}"\n   [{label}]')
            for i, h in enumerate(hits, 1):
                t, a = titles.get(str(h["mbid"]), ("(title?)", "(artist?)"))
                print(f"   {i:2}. cos={1 - float(h['distance']):.3f}  {t} — {a}")
            print()
    finally:
        await close_deps(deps)


if __name__ == "__main__":
    asyncio.run(main())
