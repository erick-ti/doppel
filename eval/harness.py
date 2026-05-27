"""Day-7 evaluation harness — drive the real pipeline over benchmark seeds and report metrics.

Mirrors the API's orchestration (`aggregate` → a `queued` query_logs row → `run_pipeline`) but in
**job mode**, so the gates never enqueue and the whole pipeline runs in-process — no worker, no
Redis. Per seed it records the persisted telemetry (`query_logs`) plus the returned results and emits:

  * **coverage** — candidate yield, resolve found/rejected/not-found, audio-scored vs cultural backfill
    (the #1 risk per BRAINDUMP: does Deezer preview coverage hold across genres?);
  * **score distributions** — raw audio / vibe-text / fused cosine ranges (does the audio leg occupy a
    different range than the vibe leg — i.e. is the within-batch min-max-then-fuse choice justified, or
    is the rank-fusion fallback warranted?);
  * **ablation** — CLAP-reranked order vs cultural-only (RRF) order: top-k overlap + how far CLAP moved
    the audio-scored tracks from their cultural rank (does the audio leg earn its keep?);
  * **latency**.

This is a diagnostic + spot-check tool, not an automated optimizer — there is no ground-truth "good
vibe match", so it informs *manual* knob choices (`RESOLVE_CANDIDATE_LIMIT`, α/β, pooling, gates).

Run (needs a live Postgres + the `clap` group + network; `LASTFM_API_KEY` in `.env` for the Last.fm
leg). Override the resolve cap for speed via the env knob:

    RESOLVE_CANDIDATE_LIMIT=20 DATABASE_URL=postgresql://doppel:doppel@localhost:5433/doppel \
        uv run --group clap python -m eval.harness --seeds pilot

The explainer is OFF by default (rationale quality isn't a calibration metric, and skipping it avoids
LLM cost/latency across many sweep runs); pass --explain to include it.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import statistics
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doppel import db
from doppel.aggregation.aggregator import Gate, aggregate, gate_for
from doppel.aggregation.ranking import RankedCandidate
from doppel.config import GATE1_ASYNC_THRESHOLD, RESOLVE_CANDIDATE_LIMIT
from doppel.db import QueryLogFields
from doppel.explanation import ClaudeExplainer
from doppel.pipeline.deps import build_deps, close_deps
from doppel.pipeline.recommend import (
    Recommendation,
    RecommendationResult,
    run_pipeline,
)
from doppel.sources.lastfm import LastFmClient
from doppel.sources.listenbrainz import ListenBrainzClient

from eval.seeds import SEED_SETS, Seed

_ABLATION_K = 10


def _stats(values: Sequence[float]) -> dict[str, float] | None:
    """min / median / max for a score column, or ``None`` when the column is empty (no such scores)."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return {
        "min": round(min(vals), 4),
        "median": round(statistics.median(vals), 4),
        "max": round(max(vals), 4),
        "n": len(vals),
    }


def _ablation(results: Sequence[RecommendationResult], pool: Sequence[RankedCandidate]) -> dict[str, Any]:
    """How much did CLAP reorder vs the cultural-only (RRF) order?

    ``topk_overlap`` — fraction of the produced top-k that the pure-cultural top-k also contains (low
    ⇒ CLAP pulled different tracks into the head). ``mean_rank_displacement`` — among the audio-scored
    tracks, the mean |CLAP-rank − cultural-rank| *within that set* (0 ⇒ CLAP kept cultural order; higher
    ⇒ more reordering). Both are ``None`` when there's nothing to compare.
    """
    cultural_ids = [(c.title, c.artist) for c in sorted(pool, key=lambda c: c.cultural_score, reverse=True)]
    produced_ids = [(r.title, r.artist) for r in results]
    k = min(_ABLATION_K, len(produced_ids), len(cultural_ids))
    overlap = len(set(produced_ids[:k]) & set(cultural_ids[:k])) / k if k else None

    audio = [r for r in results if r.was_audio_scored]
    by_cultural = sorted(audio, key=lambda r: r.cultural_score, reverse=True)
    cultural_pos = {(r.title, r.artist): i for i, r in enumerate(by_cultural)}
    disps = [abs(i - cultural_pos[(r.title, r.artist)]) for i, r in enumerate(audio)]
    return {
        "k": k,
        "topk_overlap": round(overlap, 3) if overlap is not None else None,
        "n_audio_scored": len(audio),
        "mean_rank_displacement": round(statistics.mean(disps), 2) if disps else None,
        "clap_top3": [f"{r.title} — {r.artist}" for r in results[:3]],
    }


async def run_seed(deps, sources, seed: Seed) -> dict[str, Any]:
    """Run one seed through the real pipeline (job mode) and collect its metrics. A regular failure is
    recorded as a per-seed error so the batch completes; a cancellation is re-raised so it stops the
    batch — terminalizing the in-flight row first either way."""
    started = time.monotonic()
    qid: int | None = None
    try:
        result = await aggregate(sources, seed.title, seed.artist)
        async with deps.pool.acquire() as conn:
            uncached = await db.count_uncached_candidates(
                conn, [(c.title, c.artist) for c in result.candidates[:RESOLVE_CANDIDATE_LIMIT]]
            )
            gate1 = gate_for(uncached, threshold=GATE1_ASYNC_THRESHOLD)
            # No request_key: the eval is a library driver, not a real request, and must NOT join the
            # in-flight dedup (the active-request_key unique index covers queued/running rows). The
            # index treats NULLs as distinct, so a row orphaned by a crash/cancel/SIGKILL — which the
            # running-row reaper won't touch while it's `queued` — still can't wedge a re-run or a real
            # /recommend for the same seed. (The failure path also terminalizes it, belt-and-braces.)
            qid = await db.insert_query_log(conn, QueryLogFields(
                seed_title=seed.title, seed_artist=seed.artist, vibe_text=seed.vibe, status="queued",
                candidate_count=len(result.candidates), degraded=result.degraded,
                failed_sources=result.failed_sources, gate1=gate1.value,
                gate1_threshold=GATE1_ASYNC_THRESHOLD, uncached_count=uncached,
            ))
        rec = await run_pipeline(
            deps, seed.title, seed.artist, seed.vibe, result.candidates,
            execution_mode="job", query_log_id=qid,
        )
        assert isinstance(rec, Recommendation)  # job mode never defers
        async with deps.pool.acquire() as conn:
            row = await db.get_query_log(conn, qid)
        return _metrics(seed, result.candidates, rec, row, time.monotonic() - started)
    except (Exception, asyncio.CancelledError) as exc:  # CancelledError is a BaseException — catch it too
        await _terminalize(deps, qid, seed, exc)
        if isinstance(exc, asyncio.CancelledError):
            raise  # don't swallow cancellation as a per-seed error — let it stop the batch
        return {
            "seed": seed.label, "genre": seed.genre, "ok": False,
            "error": f"{type(exc).__name__}: {exc}", "wall_s": round(time.monotonic() - started, 1),
        }


async def _terminalize(deps, qid: int | None, seed: Seed, exc: BaseException) -> None:
    """Best-effort: mark a pre-created eval row `failed` so it doesn't linger non-terminal. The NULL
    request_key already keeps an orphan from wedging dedup; this just keeps the row's status truthful."""
    if qid is None:
        return
    with contextlib.suppress(Exception):
        async with deps.pool.acquire() as conn:
            await db.update_query_log(conn, qid, QueryLogFields(
                seed_title=seed.title, seed_artist=seed.artist,
                status="failed", error=f"{type(exc).__name__}: {exc}"[:500],
            ))


def _metrics(seed: Seed, pool, rec: Recommendation, row, wall_s: float) -> dict[str, Any]:
    audio_scored = sum(1 for r in rec.results if r.was_audio_scored)
    resolved = (row["resolved_found"] or 0) + (row["resolved_rejected"] or 0) + (row["resolved_not_found"] or 0)
    return {
        "seed": seed.label, "genre": seed.genre, "ok": True, "wall_s": round(wall_s, 1),
        "seed_audio_scored": bool(row["seed_audio_scored"]),
        "coverage": {
            "candidate_count": row["candidate_count"],
            "resolve_attempted": resolved,
            "resolved_found": row["resolved_found"],
            "resolved_rejected": row["resolved_rejected"],
            "resolved_not_found": row["resolved_not_found"],
            "found_ratio": round(row["resolved_found"] / resolved, 3) if resolved else None,
            "audio_scored": audio_scored,
            "backfill": len(rec.results) - audio_scored,
            "embeddings_cache_hits": row["embeddings_cache_hits"],
            "embeddings_computed": row["embeddings_computed"],
        },
        "score_dist": {
            "audio": _stats([r.audio_score for r in rec.results]),
            "vibe_text": _stats([r.vibe_text_score for r in rec.results]),
            "combined": _stats([r.combined_score for r in rec.results]),
        },
        "ablation": _ablation(rec.results, pool),
        "latency_ms": row["latency_ms"],
    }


def _render_report(seed_set: str, rows: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    ok = [r for r in rows if r["ok"]]
    lines = [
        f"# Doppel eval — `{seed_set}` set", "",
        f"_Run {meta['ran_at']} · RESOLVE_CANDIDATE_LIMIT={meta['resolve_limit']} · "
        f"explainer={'on' if meta['explain'] else 'off'} · {len(ok)}/{len(rows)} seeds ok_", "",
        "## Per-seed", "",
        "| seed | genre | cand | found/rej/nf | audio | backfill | cache hits | top10∩cult | rank-displ | audio cos (min/med/max) | vibe cos | latency |",
        "|---|---|--|--|--|--|--|--|--|--|--|--|",
    ]
    for r in rows:
        if not r["ok"]:
            lines.append(f"| {r['seed']} | {r['genre']} | — | **ERROR**: {r['error']} | | | | | | | | |")
            continue
        c, a, s = r["coverage"], r["ablation"], r["score_dist"]
        ac = s["audio"]; vc = s["vibe_text"]
        audio_cos = f"{ac['min']}/{ac['median']}/{ac['max']}" if ac else "—"
        vibe_cos = f"{vc['min']}/{vc['median']}/{vc['max']}" if vc else "—"
        lines.append(
            f"| {r['seed']} | {r['genre']} | {c['candidate_count']} | "
            f"{c['resolved_found']}/{c['resolved_rejected']}/{c['resolved_not_found']} | "
            f"{c['audio_scored']} | {c['backfill']} | {c['embeddings_cache_hits']} | "
            f"{a['topk_overlap']} | {a['mean_rank_displacement']} | {audio_cos} | {vibe_cos} | "
            f"{r['latency_ms']}ms |"
        )
    if ok:
        found_ratios = [r["coverage"]["found_ratio"] for r in ok if r["coverage"]["found_ratio"] is not None]
        audio_seeds = sum(1 for r in ok if r["seed_audio_scored"])
        overlaps = [r["ablation"]["topk_overlap"] for r in ok if r["ablation"]["topk_overlap"] is not None]
        displ = [r["ablation"]["mean_rank_displacement"] for r in ok if r["ablation"]["mean_rank_displacement"] is not None]
        lines += [
            "", "## Aggregate (ok seeds)", "",
            f"- seed audio-scored: **{audio_seeds}/{len(ok)}** (coverage — the #1 risk)",
            f"- median resolve found-ratio: **{round(statistics.median(found_ratios), 3) if found_ratios else 'n/a'}**",
            f"- median top-10 overlap with cultural order: **{round(statistics.median(overlaps), 3) if overlaps else 'n/a'}** "
            "(lower ⇒ CLAP reranks harder)",
            f"- median audio-scored rank displacement: **{round(statistics.median(displ), 2) if displ else 'n/a'}** "
            "(0 ⇒ CLAP keeps cultural order)",
            f"- median latency: **{round(statistics.median([r['latency_ms'] for r in ok]))}ms**",
            "", "## CLAP top-3 per seed", "",
        ]
        lines += [f"- **{r['seed']}** → {', '.join(r['ablation']['clap_top3'])}" for r in ok]
    return "\n".join(lines) + "\n"


async def main() -> None:
    p = argparse.ArgumentParser(description="Doppel Day-7 evaluation harness")
    p.add_argument("--seeds", choices=list(SEED_SETS), default="pilot")
    p.add_argument("--explain", action="store_true",
                   help="include the LLM explainer (off by default — rationales aren't a calibration metric)")
    p.add_argument("--out", default="eval/reports")
    args = p.parse_args()
    seeds = SEED_SETS[args.seeds]

    deps = await build_deps(enqueue_job=None)
    if not args.explain:
        # Drop the explainer (closing the client build_deps opened) — no LLM calls; rationales aren't
        # an eval metric and skipping them saves cost/latency across the many sweep runs to come.
        if isinstance(deps.explainer, ClaudeExplainer):
            await deps.explainer.aclose()
        deps.explainer = None
    sources = [ListenBrainzClient(deps.http), LastFmClient(deps.http)]

    rows: list[dict[str, Any]] = []
    try:
        for i, seed in enumerate(seeds, 1):
            print(f"[{i}/{len(seeds)}] {seed.label} …", flush=True)
            row = await run_seed(deps, sources, seed)
            tag = "ok" if row["ok"] else f"ERROR {row['error']}"
            print(f"    {tag}  ({row['wall_s']}s)", flush=True)
            rows.append(row)
    finally:
        await close_deps(deps)

    meta = {
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed_set": args.seeds, "resolve_limit": RESOLVE_CANDIDATE_LIMIT, "explain": args.explain,
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = out_dir / f"eval-{args.seeds}-{stamp}"
    base.with_suffix(".json").write_text(json.dumps({"meta": meta, "results": rows}, indent=2))
    report = _render_report(args.seeds, rows, meta)
    base.with_suffix(".md").write_text(report)
    print("\n" + report)
    print(f"written: {base}.md / .json")


if __name__ == "__main__":
    asyncio.run(main())
