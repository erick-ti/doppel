"""Export curated-seed recommendations to static JSON for the v1.1 showcase frontend.

The showcase site (``web/``) is **fully static**: no live backend, no request-time inference. This
script regenerates a full :class:`RecommendationResponse` body — *with* LLM rationales — for each
curated seed by running the **real pipeline** in job mode (the same path the eval harness drives), then
writes one ``<slug>.json`` per seed into ``web/public/seeds/``. The Next.js app imports those at build
time. Every shipped number is therefore a serialization of real persisted pipeline output, stamped with
the git SHA + model version it came from (invariant #2: the JSON carries Deezer track-*page* links and
derived scores — never audio, never preview URLs).

Why regenerate rather than reuse ``eval/reports/*.json``? Those eval runs were ``--explain`` OFF, so
they carry only aggregate diagnostics (coverage/score_dist/ablation) — **no** ``ResultItem`` rows, no
``deezer_url``, no rationales. The showcase needs the full per-result body, so it must be re-run.

Run on the VPS (where the corpus is already warm from the eval runs) over the SSH tunnel, with the
``clap`` group and the live keys present::

    LASTFM_API_KEY=… ANTHROPIC_API_KEY=… DATABASE_URL=… \\
        uv run --group clap python scripts/export_showcase.py

First run of an uncached seed pays the ~701 s cold path once; a warm seed exports in ~12 s. Use
``--only <slug,…>`` to (re)run a subset, and ``--degraded "Title::Artist"`` to capture one
intentionally-degraded (no-seed-preview → cultural-only) response for the System-Transparency panel.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doppel import db
from doppel.aggregation.aggregator import aggregate, gate_for
from doppel.api.responses import response_from_rows
from doppel.config import (
    AUDIO_SIM_WEIGHT,
    CLAP_MODEL_VERSION,
    GATE1_ASYNC_THRESHOLD,
    RESOLVE_CANDIDATE_LIMIT,
    VIBE_TEXT_WEIGHT,
)
from doppel.db import QueryLogFields
from doppel.pipeline.deps import build_deps, close_deps
from doppel.pipeline.recommend import Recommendation, run_pipeline
from doppel.sources.lastfm import LastFmClient
from doppel.sources.listenbrainz import ListenBrainzClient


@dataclass(frozen=True)
class ShowcaseSeed:
    """A curated seed to export. ``slug`` names its ``<slug>.json`` and the frontend route."""

    slug: str
    title: str
    artist: str
    genre: str
    vibe: str | None = None
    expect_degraded: bool = False  # the intentionally-degraded capture runs a different gate profile


# The 8 genre heroes + 2 vibe-steer variants (see V1.1_SHOWCASE_PLAN.md §3). Titles/artists match
# eval/seeds.py FULL_SEEDS verbatim so this aligns with the verified warm benchmark run.
CURATED: list[ShowcaseSeed] = [
    ShowcaseSeed("blinding-lights", "Blinding Lights", "The Weeknd", "pop"),
    ShowcaseSeed("cranes-in-the-sky", "Cranes in the Sky", "Solange", "r&b"),
    ShowcaseSeed("humble", "HUMBLE.", "Kendrick Lamar", "hip-hop"),
    ShowcaseSeed("the-less-i-know-the-better", "The Less I Know the Better", "Tame Impala", "indie"),
    ShowcaseSeed("midnight-city", "Midnight City", "M83", "electronic"),
    ShowcaseSeed("take-five", "Take Five", "The Dave Brubeck Quartet", "jazz"),
    ShowcaseSeed("dreams", "Dreams", "Fleetwood Mac", "pre-2000"),
    ShowcaseSeed("despacito", "Despacito", "Luis Fonsi", "non-english"),
    # Vibe-steer pair: HUMBLE. plain (above) vs steered — the hero, the only seed whose text leg
    # visibly reshuffles the top-3 (text cosine band 0.28–0.37).
    ShowcaseSeed("humble-vibe-acoustic", "HUMBLE.", "Kendrick Lamar", "hip-hop",
                 vibe="stripped back, acoustic, intimate"),
    # Second, honestly-subtle vibe example.
    ShowcaseSeed("midnight-city-vibe-latenight", "Midnight City", "M83", "electronic",
                 vibe="melancholic, late-night driving"),
]


def _git_sha() -> str:
    """Short HEAD SHA so each export is honestly dated to a pipeline state (``unknown`` off-repo)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip() or "unknown"
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def _git_dirty() -> bool:
    """True if any *tracked* file differs from HEAD — then ``git_sha`` is not a clean, reproducible
    commit. A soft provenance flag (not a gate): it keeps the stamp honest rather than blocking work."""
    try:
        return subprocess.run(["git", "diff", "--quiet"]).returncode != 0
    except OSError:
        return False


def _coverage(rec: Recommendation, row) -> dict[str, Any]:
    """The candidate funnel, straight from the persisted query_logs row — drives the funnel animation:
    candidate_count → resolve_attempted → found/rejected/not_found → audio_scored → (backfill)."""
    audio_scored = sum(1 for r in rec.results if r.was_audio_scored)
    resolved = (row["resolved_found"] or 0) + (row["resolved_rejected"] or 0) + (row["resolved_not_found"] or 0)
    return {
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
        "latency_ms": row["latency_ms"],
    }


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


_SCORE_FIELDS = ("audio_score", "vibe_text_score", "combined_score", "cultural_score")
_SCORE_PRECISION = 6  # absorbs the ~1e-8 CLAP/cosine CPU float noise so re-exports don't churn


def _round_scores(payload: dict[str, Any]) -> dict[str, Any]:
    """Round result scores to a fixed precision so re-exports are reproducible — CLAP/cosine carry
    ~1e-8 float noise run-to-run on CPU. 6 dp is far beyond the 2–3 the UI shows and preserves the
    ordering; null scores (cultural-backfill rows, no-vibe runs) are left untouched (never rounded)."""
    for r in payload["results"]:
        for k in _SCORE_FIELDS:
            if r.get(k) is not None:
                r[k] = round(r[k], _SCORE_PRECISION)
    return payload


def _gate_report(seed: ShowcaseSeed, payload: dict[str, Any]) -> dict[str, bool]:
    """The quality checks that back the showcase's public claims (see plan §3). Evaluated per-profile
    by :func:`_gates_pass`; for a curated seed any failure aborts the run (the JSON is written but the
    batch exits nonzero so it is not committed) unless ``--allow-gate-warnings`` is passed."""
    deg = payload["degradation"]
    results = payload["results"]
    # A same-title result is a likely self/master leak the PR-#12 suppression should have dropped
    # (e.g. Take Five → "Take Five — Dave Brubeck"). Title-only match is the strong signal regardless
    # of the artist-credit variant.
    self_titles = [r for r in results if _norm(r["title"]) == _norm(seed.title)]
    return {
        "seed_audio_scored": bool(deg["seed_audio_scored"]),
        "no_cultural_backfill": deg["cultural_backfill_count"] == 0,
        "rationales_available": bool(deg["rationales_available"]),
        "no_degraded_sources": not deg["degraded_sources"],
        "no_self_master_leak": not self_titles,
    }


def _gates_pass(seed: ShowcaseSeed, gates: dict[str, bool]) -> tuple[bool, list[str]]:
    """Evaluate the gate set against the seed's profile, returning ``(passed, problems)``.

    Curated seeds must pass *every* gate — they back the showcase's public claims. The intentionally
    -degraded capture is the inverse: it MUST come back cultural-only (to power the System-Transparency
    demo), so it requires the seed *not* audio-scored AND ``no_degraded_sources`` (a degraded source's
    raw error string can carry a provider URL/credential and is never published); the *other* curated
    gates deliberately don't apply, since a degraded run has cultural backfill and may carry no rationales.
    """
    if seed.expect_degraded:
        problems = []
        if gates["seed_audio_scored"]:
            problems.append("expected a cultural-only (no-preview) capture, but the seed WAS audio-scored")
        if not gates["no_degraded_sources"]:
            problems.append("no_degraded_sources")  # never publish a raw provider error string
        return (not problems), problems
    problems = [name for name, ok in gates.items() if not ok]
    return (not problems), problems


# Only these "cosmetic" gates may be force-written by --allow-gate-warnings. The MATERIAL gates —
# seed_audio_scored (a curated seed must be audio-scored / a degraded capture must be cultural-only,
# carried as the degraded-profile mismatch message) and no_degraded_sources (a provider error string
# is never public) — are NEVER overridable, because they back the showcase's core claims, not polish.
_OVERRIDABLE_GATES = frozenset({"no_cultural_backfill", "rationales_available", "no_self_master_leak"})


def _should_write(passed: bool, problems: list[str], *, allow_gate_warnings: bool) -> bool:
    """Whether to write a seed's JSON to the (public, committable) output dir.

    Write when the gate profile passes. ``--allow-gate-warnings`` force-writes a seed whose ONLY
    failures are cosmetic (:data:`_OVERRIDABLE_GATES`) for exploratory runs — but a *material* failure
    (a non-audio-scored curated seed / an audio-scored degraded capture / any degraded source) is never
    overridable, so the override can't quietly publish output that breaks the showcase's claims.
    """
    if passed:
        return True
    return allow_gate_warnings and all(p in _OVERRIDABLE_GATES for p in problems)


def _remove_stale(path: Path) -> bool:
    """Remove a stale target file so a blocked or errored seed leaves the public set fail-closed —
    every selected seed ends up current-and-passing or absent, never a prior run's JSON. Returns
    ``True`` if a file was removed."""
    if path.exists():
        path.unlink()
        return True
    return False


async def _terminalize(deps, qid: int | None, seed: ShowcaseSeed, exc: BaseException) -> None:
    """Mark a pre-created queued row ``failed`` so a per-seed error doesn't linger non-terminal. The
    NULL request_key (no request_key passed below) already keeps an orphan out of the in-flight dedup."""
    if qid is None:
        return
    with contextlib.suppress(Exception):
        async with deps.pool.acquire() as conn:
            await db.update_query_log(conn, qid, QueryLogFields(
                seed_title=seed.title, seed_artist=seed.artist,
                status="failed", error=f"{type(exc).__name__}: {exc}"[:500],
            ))


async def export_seed(
    deps, sources, seed: ShowcaseSeed, out_dir: Path, sha: str, *, allow_gate_warnings: bool = False
) -> dict[str, Any]:
    """Run one seed through the real pipeline (job mode, explainer ON) and write ``<slug>.json``.

    Mirrors eval.harness.run_seed's orchestration: aggregate → count uncached → Gate 1 → insert a
    ``queued`` row → run_pipeline(job) → reload the row + result snapshot. Serializes via the shared
    ``response_from_rows`` builder (so degraded_sources reflects the durable row), augments with
    coverage + a staleness stamp, and writes the file only when :func:`_should_write` allows it — a
    payload with a degraded source never lands on disk, even under ``allow_gate_warnings``. When a
    selected seed is blocked or errors, any stale ``<slug>.json`` is removed (fail-closed: the public
    set stays current-and-passing or absent, never a prior run's JSON).
    """
    started = time.monotonic()
    qid: int | None = None
    path = out_dir / f"{seed.slug}.json"
    try:
        agg = await aggregate(sources, seed.title, seed.artist)
        async with deps.pool.acquire() as conn:
            uncached = await db.count_uncached_candidates(
                conn, [(c.title, c.artist) for c in agg.candidates[:RESOLVE_CANDIDATE_LIMIT]]
            )
            gate1 = gate_for(uncached, threshold=GATE1_ASYNC_THRESHOLD)
            # No request_key — like the eval harness, this is a library driver, not a real request, and
            # must not join the in-flight /recommend dedup.
            qid = await db.insert_query_log(conn, QueryLogFields(
                seed_title=seed.title, seed_artist=seed.artist, vibe_text=seed.vibe, status="queued",
                candidate_count=len(agg.candidates), degraded=agg.degraded,
                failed_sources=agg.failed_sources, gate1=gate1.value,
                gate1_threshold=GATE1_ASYNC_THRESHOLD, uncached_count=uncached,
            ))
        rec = await run_pipeline(
            deps, seed.title, seed.artist, seed.vibe, agg.candidates,
            execution_mode="job", query_log_id=qid,
        )
        assert isinstance(rec, Recommendation)  # job mode never defers
        async with deps.pool.acquire() as conn:
            row = await db.get_query_log(conn, qid)
            results = await db.get_query_log_results(conn, qid)

        # Serialize from the DURABLE row + result snapshot, NOT the in-memory Recommendation. In job
        # mode that Recommendation carries degraded_sources={} (it is derived from the omitted gate1),
        # so serializing it would silently hide a real cultural-source failure and make the
        # no_degraded_sources gate a no-op. The row's failed_sources is the source of truth — and this
        # makes the export byte-identical to production's COLD-poll body (response_from_rows).
        payload = response_from_rows(row, results).model_dump(mode="json")
        _round_scores(payload)  # reproducible re-exports — absorb sub-1e-8 score noise (export-only)
        payload["coverage"] = _coverage(rec, row)
        payload["meta"] = {
            "slug": seed.slug, "genre": seed.genre,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_sha": sha, "git_dirty": _git_dirty(), "clap_model_version": CLAP_MODEL_VERSION,
            "alpha": AUDIO_SIM_WEIGHT, "beta": VIBE_TEXT_WEIGHT,
            "resolve_candidate_limit": RESOLVE_CANDIDATE_LIMIT,
        }

        gates = _gate_report(seed, payload)
        passed, problems = _gates_pass(seed, gates)
        # Write only when the gate profile allows it. --allow-gate-warnings can force-write a seed that
        # fails a *cosmetic* gate for exploratory runs, but no_degraded_sources is NEVER overridable —
        # a degraded source's raw error string must never reach the public output (flag or no flag).
        wrote = _should_write(passed, problems, allow_gate_warnings=allow_gate_warnings)
        removed_stale = False
        if wrote:
            out_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        else:
            removed_stale = _remove_stale(path)  # fail-closed: a blocked seed leaves no stale public file
        wall = round(time.monotonic() - started, 1)
        return {"slug": seed.slug, "label": seed.title, "ok": True,
                "path": str(path) if wrote else None, "wrote": wrote, "removed_stale": removed_stale,
                "gates": gates, "gates_pass": passed, "gate_problems": problems,
                "wall_s": wall, "results": len(payload["results"])}
    except (Exception, asyncio.CancelledError) as exc:
        await _terminalize(deps, qid, seed, exc)
        if isinstance(exc, asyncio.CancelledError):
            raise
        removed_stale = _remove_stale(path)  # fail-closed: an errored seed leaves no stale public file
        return {"slug": seed.slug, "label": seed.title, "ok": False, "removed_stale": removed_stale,
                "error": f"{type(exc).__name__}: {exc}", "wall_s": round(time.monotonic() - started, 1)}


def _select(only: str | None, degraded: str | None) -> list[ShowcaseSeed]:
    """Resolve the roster to run: the curated set (optionally filtered by ``--only``) plus an optional
    operator-supplied ``--degraded "Title::Artist"`` capture written as ``degraded.json``."""
    seeds = list(CURATED)
    if only:
        wanted = {s.strip() for s in only.split(",") if s.strip()}
        unknown = wanted - {s.slug for s in seeds}
        if unknown:
            raise SystemExit(f"unknown slug(s): {', '.join(sorted(unknown))}; "
                             f"known: {', '.join(s.slug for s in CURATED)}")
        seeds = [s for s in seeds if s.slug in wanted]
    if degraded:
        title, _, artist = degraded.partition("::")
        if not (title and artist):
            raise SystemExit('--degraded expects "Title::Artist"')
        seeds.append(ShowcaseSeed("degraded", title.strip(), artist.strip(), "degraded-demo",
                                  expect_degraded=True))
    return seeds


async def main() -> None:
    p = argparse.ArgumentParser(description="Export curated-seed recommendations for the v1.1 showcase")
    p.add_argument("--out", default="web/public/seeds", help="output dir for <slug>.json (default web/public/seeds)")
    p.add_argument("--only", help="comma-separated slug subset to (re)run (default: all curated seeds)")
    p.add_argument("--degraded", metavar='"Title::Artist"',
                   help="also capture one intentionally-degraded (no-preview → cultural-only) response as degraded.json")
    p.add_argument("--allow-gate-warnings", action="store_true",
                   help="exploratory pass: write + exit 0 on a COSMETIC gate failure (backfill / rationales "
                        "/ self-master); no_degraded_sources stays enforced. Such output must NOT be committed.")
    args = p.parse_args()

    seeds = _select(args.only, args.degraded)
    out_dir = Path(args.out)
    sha = _git_sha()

    # Explainer stays ON (build_deps opens it) — rationales are a first-class showcase surface, unlike
    # the eval harness which drops it.
    deps = await build_deps(enqueue_job=None)
    sources = [ListenBrainzClient(deps.http), LastFmClient(deps.http)]

    rows: list[dict[str, Any]] = []
    try:
        for i, seed in enumerate(seeds, 1):
            label = seed.title + (f" [vibe: {seed.vibe}]" if seed.vibe else "")
            print(f"[{i}/{len(seeds)}] {seed.slug}: {label} …", flush=True)
            row = await export_seed(deps, sources, seed, out_dir, sha,
                                    allow_gate_warnings=args.allow_gate_warnings)
            stale_note = "  [removed stale file]" if row.get("removed_stale") else ""
            if not row["ok"]:
                print(f"    ERROR {row['error']}  ({row['wall_s']}s){stale_note}", flush=True)
            elif row["wrote"]:
                badge = ("✓ gates ok" if row["gates_pass"]
                         else f"⚠ written despite GATE FAIL ({', '.join(row['gate_problems'])}) via --allow-gate-warnings")
                print(f"    wrote {row['path']}  ({row['results']} results, {row['wall_s']}s)  {badge}", flush=True)
            else:
                print(f"    GATE FAIL — not written: {', '.join(row['gate_problems'])}  ({row['wall_s']}s){stale_note}", flush=True)
            rows.append(row)
    finally:
        await close_deps(deps)

    ok = [r for r in rows if r["ok"]]
    gate_fail = [r for r in ok if not r["gates_pass"]]
    print(f"\nexported {len(ok)}/{len(rows)} seeds → {out_dir}  "
          f"({len(ok) - len(gate_fail)} passed gates / {len(gate_fail)} failed)")
    if len(ok) != len(rows):
        raise SystemExit(1)  # a seed hard-errored — incomplete batch
    if gate_fail and not args.allow_gate_warnings:
        fails = ", ".join(r["slug"] for r in gate_fail)
        raise SystemExit(
            f"gate failures on: {fails} (not written). Fix the seed(s), or re-run with "
            f"--allow-gate-warnings to write them anyway (exploratory only — never commit such output)."
        )


if __name__ == "__main__":
    asyncio.run(main())
