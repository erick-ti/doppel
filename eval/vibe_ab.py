"""v2 Phase 1 — the vibe→acoustic-translation measurement instrument (eval-only).

The flagship of v2 ("deepen the engine") is an LLM step that rewrites a natural-language vibe
("sad late-night driving") into the literal acoustic vocabulary CLAP was trained on ("slow tempo,
minor key, sparse reverb-heavy downtempo") *before* CLAP text-encoding. The Day-7 eval proved CLAP's
text encoder is weak on cultural descriptors (vibe-text cosines ~0.15–0.37, semantically
inconsistent), so the translation *might* help — but "did the vibe steer correctly?" has no labelled
ground truth.

This module builds the **label-free ship gate** that decides the flagship before it is wired into the
pipeline (DECISIONS.md 2026-05-31). It exploits the eval's proven asymmetry: audio-to-audio cosine
(~0.8) is reliable, so the **audio-reranked order is a silent proxy for correct steering**. For one
already-resolved + already-embedded candidate batch we score it twice via the existing pure-numpy
:func:`~doppel.embedding.scoring.score_candidates` — swapping *only* the text vector (raw vibe vs
translated vibe) — and compute four lifts:

  1. **magnitude_lift** — does the translated vibe raise the median text-cosine over the ~0.15–0.37
     baseline? (it should clear the wall the encoder hit on raw cultural language)
  2. **agreement_lift** — does the translated text's per-candidate ranking agree *more* with the
     reliable audio ranking (Spearman)? This is the real correctness proxy.
  3. **spread guard** — does the translated text still *discriminate* (spread of cosines doesn't
     collapse)? Catches the dangerous null where translation adds a uniform constant, not steering.
  4. **topn_overlap** — raw vs translated top-N by fused score; a pure delta-detector (≈1.0 ⇒ changed
     nothing).

SHIP RULE (conjunctive, falsifiable): the flagship ships default-on iff (1) AND (2) improve WHILE (3)
holds. Cosines up but agreement flat ⇒ inflation, not steering ⇒ REJECT. The audio matrix is
arm-independent, nothing is re-resolved or re-embedded, and the ``embeddings`` cache / ``model_version``
are untouched — so this is a measurement, not a contract change (invariant #4 does not fire).

The pure metric core (:func:`vibe_ab_metrics`, :func:`spearman`) is offline + unit-tested
(``tests/test_vibe_ab.py``). The driver (:func:`run_vibe_ab_seed`, :func:`main`) needs a live Postgres
+ the ``clap`` group + network, exactly like ``eval.harness``:

    RESOLVE_CANDIDATE_LIMIT=20 DATABASE_URL=postgresql://doppel:doppel@localhost:5433/doppel \
        uv run --group clap python -m eval.vibe_ab --seeds full

In Phase 1 the *translated* arm comes from a hand-authored placeholder map below (enough to validate
that the instrument discriminates). Phase 2 swaps in the real ``VibeTranslator`` by passing a
``translate`` callable to :func:`run_vibe_ab_seed` — that re-run produces the actual ship decision.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from doppel import db
from doppel.config import CLAP_MODEL_VERSION, RESOLVE_CANDIDATE_LIMIT
from doppel.embedding.scoring import score_candidates
from doppel.explanation import ClaudeExplainer
from doppel.pipeline.deps import build_deps, close_deps
from doppel.pipeline.recommend import Recommendation, run_pipeline
from doppel.sources.lastfm import LastFmClient
from doppel.sources.listenbrainz import ListenBrainzClient
from doppel.translation import ClaudeVibeTranslator

from eval.harness import _open_query_log, _terminalize
from eval.seeds import SEED_SETS, Seed

_TOP_N = 10
# Translated arm collapses if its cosine spread falls below this fraction of the raw arm's spread —
# i.e. the translation stopped discriminating between candidates (added a constant, not steering).
_SPREAD_COLLAPSE_RATIO = 0.5


# ── pure metric core (offline, unit-tested) ──────────────────────────────────────────────────────

def _ranks(xs: Sequence[float]) -> list[float]:
    """Average (tie-aware) ranks of ``xs`` — equal values share the mean of the positions they span."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0  # mean position of the tied run i..j
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Pearson correlation, or ``None`` when either series has zero variance (correlation undefined)."""
    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx <= 0.0 or vy <= 0.0:
        return None
    return cov / ((vx * vy) ** 0.5)


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Spearman rank correlation in [-1, 1] (Pearson on tie-averaged ranks).

    ``None`` when the series differ in length, have fewer than two points, or one is constant — all
    cases where a rank correlation carries no signal.
    """
    if len(a) != len(b) or len(a) < 2:
        return None
    return _pearson(_ranks(a), _ranks(b))


def vibe_ab_metrics(
    seed_audio: Any,
    candidate_audios: Sequence[Any],
    raw_vibe_vec: Any,
    translated_vibe_vec: Any,
    *,
    top_n: int = _TOP_N,
    spread_collapse_ratio: float = _SPREAD_COLLAPSE_RATIO,
) -> dict[str, Any] | None:
    """Two-arm A/B over one embedded batch — raw-vibe vs translated-vibe — and the four lift metrics.

    ``seed_audio`` and each ``candidate_audios`` entry are 512-dim CLAP *audio* vectors;
    ``raw_vibe_vec`` / ``translated_vibe_vec`` are CLAP *text* vectors. The audio-to-audio cosines are
    identical across arms (same seed + candidates), so they serve as the fixed ground-truth proxy the
    two text arms are judged against. ``None`` when the batch is empty.
    """
    candidates = list(candidate_audios)
    n = len(candidates)
    if n == 0:
        return None

    raw = score_candidates(seed_audio, candidates, vibe_text=raw_vibe_vec)
    tr = score_candidates(seed_audio, candidates, vibe_text=translated_vibe_vec)

    by_index_raw = sorted(raw, key=lambda s: s.index)
    by_index_tr = sorted(tr, key=lambda s: s.index)
    audio = [s.audio_similarity for s in by_index_raw]  # arm-independent: same seed + candidates
    raw_text = [float(s.text_similarity) for s in by_index_raw]
    tr_text = [float(s.text_similarity) for s in by_index_tr]

    # (1) magnitude lift — did the translated vibe clear the ~0.15–0.37 raw-cosine wall?
    raw_med = statistics.median(raw_text)
    tr_med = statistics.median(tr_text)
    magnitude_lift = tr_med - raw_med

    # (2) agreement lift — did the translated text rank candidates more like the reliable audio order?
    sp_raw = spearman(raw_text, audio)
    sp_tr = spearman(tr_text, audio)
    agreement_lift = (sp_tr - sp_raw) if (sp_raw is not None and sp_tr is not None) else None

    # (3) spread guard — did the translated text keep discriminating, or collapse to a constant?
    raw_spread = max(raw_text) - min(raw_text)
    tr_spread = max(tr_text) - min(tr_text)
    spread_ok = tr_spread >= spread_collapse_ratio * raw_spread if raw_spread > 0 else tr_spread > 0

    # (4) top-N overlap — pure delta detector over the fused order (score_candidates sorts desc)
    k = min(top_n, n)
    raw_top = {s.index for s in raw[:k]}
    tr_top = {s.index for s in tr[:k]}
    topn_overlap = len(raw_top & tr_top) / k

    gate_pass = bool(
        magnitude_lift > 0
        and agreement_lift is not None
        and agreement_lift > 0
        and spread_ok
    )
    return {
        "n": n,
        "raw_text_median": round(raw_med, 4),
        "translated_text_median": round(tr_med, 4),
        "magnitude_lift": round(magnitude_lift, 4),
        "spearman_raw": round(sp_raw, 4) if sp_raw is not None else None,
        "spearman_translated": round(sp_tr, 4) if sp_tr is not None else None,
        "agreement_lift": round(agreement_lift, 4) if agreement_lift is not None else None,
        "raw_spread": round(raw_spread, 4),
        "translated_spread": round(tr_spread, 4),
        "spread_ok": spread_ok,
        "topn_overlap": round(topn_overlap, 3),
        "gate_pass": gate_pass,
    }


def beta_sensitivity(
    seed_audio: Any,
    candidate_audios: Sequence[Any],
    vibe_vec: Any,
    *,
    betas: Sequence[float],
    top_n: int = _TOP_N,
) -> list[dict[str, Any]] | None:
    """How far the fused top-N is pulled off the pure-audio top-N as the vibe weight β rises.

    Sweeps the convex fusion ``combined = (1-β)·norm_audio + β·norm_text``. β=0 is pure audio (the
    sonic baseline / fidelity anchor); higher β lets the weak (~0.2-cosine) text leg override it.
    This is what answers "can the vibe move the output at all, and at what audio-fidelity cost?" — the
    risk the first A/B exposed: at the production β=0.3 the top-10 barely budged. Per β:
      * ``overlap_vs_audio`` — |top-N(β) ∩ top-N(audio-only)| / N. 1.0 ⇒ the vibe changed nothing;
        lower ⇒ the vibe is steering the output away from the sonic baseline.
      * ``mean_audio_cos_topN`` / ``min_audio_cos_topN`` — the audio fidelity of the chosen top-N (how
        sonically close to the seed the surviving tracks are); these fall as β promotes
        vibe-matching-but-sonically-distant tracks — the fidelity cost of steering.
    Returns one dict per β; ``None`` for an empty batch.
    """
    cands = list(candidate_audios)
    n = len(cands)
    if n == 0:
        return None
    k = min(top_n, n)
    audio_only = score_candidates(seed_audio, cands)  # β=0 baseline (no vibe leg)
    audio_top = {s.index for s in audio_only[:k]}
    audio_cos = {s.index: s.audio_similarity for s in audio_only}
    rows = []
    for b in betas:
        scored = score_candidates(seed_audio, cands, vibe_text=vibe_vec, alpha=1.0 - b, beta=b)
        top = [s.index for s in scored[:k]]
        rows.append({
            "beta": round(b, 2),
            "overlap_vs_audio": round(len(set(top) & audio_top) / k, 3),
            "mean_audio_cos_topN": round(sum(audio_cos[i] for i in top) / k, 4),
            "min_audio_cos_topN": round(min(audio_cos[i] for i in top), 4),
        })
    return rows


# ── Phase-1 placeholder translations ─────────────────────────────────────────────────────────────
# Hand-authored acoustic rewrites for the benchmark vibe seeds — JUST enough to prove the instrument
# discriminates. Phase 2 replaces this with the real LLM VibeTranslator (pass a `translate` callable
# to run_vibe_ab_seed); that re-run produces the actual ship decision. Keyed (title, artist, vibe).
_PLACEHOLDER_TRANSLATIONS: dict[tuple[str, str, str], str] = {
    ("Midnight City", "M83", "melancholic, late-night driving"):
        "slow tempo, minor key, lush reverb-drenched synth pads, dreamy atmospheric, downtempo, wistful",
    ("HUMBLE.", "Kendrick Lamar", "stripped back, acoustic, intimate"):
        "sparse acoustic guitar, soft close-mic vocals, minimal percussion, warm, quiet, unplugged",
    ("Take Five", "The Dave Brubeck Quartet", "rainy day, contemplative"):
        "mellow jazz, brushed drums, soft piano, relaxed mid-tempo, melancholic, introspective, sparse",
}


# ── driver (needs Postgres + the clap group + network; operator-run) ──────────────────────────────

async def run_vibe_ab_seed(
    deps,
    sources,
    seed: Seed,
    translated_vibe: str,
    *,
    translate: Callable[[str], Awaitable[str]] | None = None,
) -> dict[str, Any]:
    """Warm one vibe seed through the real pipeline, then A/B raw-vs-translated on its embedded batch.

    ``translated_vibe`` is the precomputed translated arm (Phase 1 placeholder). Phase 2 may instead
    pass ``translate`` — a callable mapping the raw vibe to acoustic terms (the real ``VibeTranslator``)
    — which takes precedence. Mirrors ``eval.harness.run_seed``'s error discipline: a regular failure
    becomes a per-seed error row; a cancellation re-raises to stop the batch; the in-flight row is
    terminalized either way.
    """
    started = time.monotonic()
    qid: int | None = None
    if seed.vibe is None:
        return {"seed": seed.label, "genre": seed.genre, "ok": False,
                "error": "seed has no vibe to translate", "wall_s": 0.0}
    arm_translated = await translate(seed.vibe) if translate is not None else translated_vibe
    try:
        qid, result = await _open_query_log(deps, sources, seed)
        rec = await run_pipeline(
            deps, seed.title, seed.artist, seed.vibe, result.candidates,
            execution_mode="job", query_log_id=qid,
        )
        assert isinstance(rec, Recommendation)  # job mode never defers

        if rec.seed_mbid is None:
            return {"seed": seed.label, "genre": seed.genre, "ok": False,
                    "error": "cultural-only run — seed has no audio embedding to A/B against",
                    "wall_s": round(time.monotonic() - started, 1)}

        # Reconstruct the FULL embedded candidate batch — every top-N cultural candidate that resolved
        # FOUND and embedded — NOT rec.results (capped at RECOMMENDATION_LIMIT=10 AND already selected
        # by the raw-vibe fused ranking, which would bias the A/B: the translated arm could only
        # reorder the raw arm's winners, never surface a track raw excluded). Read the cached canonical
        # MBIDs (no re-resolve — warm canonical_lookups), then bulk-fetch their vectors. We require
        # status=='found' (a `rejected` lookup also carries an MBID; fetch_embeddings' servable filter
        # would drop it anyway, but filtering here is explicit and excludes the cross-query servable edge).
        # FIDELITY LIMITATION (Codex review 2026-05-31): this batch does NOT replicate _build_results'
        # provider_track_id dedup or seed-equivalence suppression (a ~0.98-audio near-master of the seed
        # that production drops can still enter here and skew the audio-rank proxy). Immaterial to the
        # disconfirmed-flagship verdict (translation's magnitude drop is large and robust), but if this
        # instrument is ever resurrected for a narrow-descriptive pass, route the batch through a shared
        # scorable-resolved helper extracted from _build_results.
        top_pool = result.candidates[:RESOLVE_CANDIDATE_LIMIT]
        async with deps.pool.acquire() as conn:
            seed_row = await db.get_embedding(conn, rec.seed_mbid, CLAP_MODEL_VERSION)
            mbids: list[str] = []
            for c in top_pool:
                look = await db.get_canonical_lookup(conn, c.title, c.artist)  # filters RESOLVER_VERSION internally
                if look is not None and look["status"] == "found" and look["mbid"] is not None:
                    m = str(look["mbid"])
                    if m != rec.seed_mbid:  # never score the seed against itself
                        mbids.append(m)
            cand_rows = await db.fetch_embeddings(conn, list(dict.fromkeys(mbids)), CLAP_MODEL_VERSION)
        if seed_row is None:
            return {"seed": seed.label, "genre": seed.genre, "ok": False,
                    "error": "seed embedding missing from corpus",
                    "wall_s": round(time.monotonic() - started, 1)}

        seed_audio = np.asarray(seed_row["embedding"], dtype=np.float64)
        candidate_audios = [np.asarray(row["embedding"], dtype=np.float64) for row in cand_rows]
        if len(candidate_audios) < 2:
            return {"seed": seed.label, "genre": seed.genre, "ok": False,
                    "error": f"only {len(candidate_audios)} embedded candidate(s) in the warm batch — too few to A/B",
                    "wall_s": round(time.monotonic() - started, 1)}

        # embed both text arms (CPU/torch-bound → off the event loop, as run_pipeline does)
        raw_vec = await asyncio.to_thread(deps.embedder.embed_text, seed.vibe)
        tr_vec = await asyncio.to_thread(deps.embedder.embed_text, arm_translated)

        metrics = vibe_ab_metrics(seed_audio, candidate_audios, raw_vec, tr_vec)
        betas = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0]
        beta_translated = beta_sensitivity(seed_audio, candidate_audios, tr_vec, betas=betas)
        beta_raw = beta_sensitivity(seed_audio, candidate_audios, raw_vec, betas=betas)
        return {
            "seed": seed.label, "genre": seed.genre, "ok": True,
            "wall_s": round(time.monotonic() - started, 1),
            "raw_vibe": seed.vibe, "translated_vibe": arm_translated,
            "metrics": metrics,
            "beta_translated": beta_translated, "beta_raw": beta_raw,
        }
    except (Exception, asyncio.CancelledError) as exc:  # CancelledError is a BaseException — catch it too
        await _terminalize(deps, qid, seed, exc)
        if isinstance(exc, asyncio.CancelledError):
            raise
        return {"seed": seed.label, "genre": seed.genre, "ok": False,
                "error": f"{type(exc).__name__}: {exc}", "wall_s": round(time.monotonic() - started, 1)}


def _render_report(seed_set: str, rows: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    ok = [r for r in rows if r["ok"]]
    passed = [r for r in ok if r["metrics"] and r["metrics"]["gate_pass"]]
    lines = [
        f"# Doppel v2 vibe-translation A/B — `{seed_set}` set", "",
        f"_Run {meta['ran_at']} · source={meta['translation_source']} · {len(ok)}/{len(rows)} seeds ok · "
        f"**{len(passed)}/{len(ok)} pass the ship gate**_", "",
        "Gate = magnitude_lift > 0 AND agreement_lift > 0 (Spearman vs audio order) WHILE spread holds. "
        "Inflation without agreement ⇒ reject.", "",
        "## Per-seed", "",
        "| seed | n | raw→tr median | magnitude lift | spearman raw→tr | agreement lift | spread raw→tr | top10∩ | GATE |",
        "|---|--|--|--|--|--|--|--|--|",
    ]
    for r in rows:
        if not r["ok"]:
            lines.append(f"| {r['seed']} | — | **ERROR**: {r['error']} | | | | | | |")
            continue
        m = r["metrics"]
        if not m:
            lines.append(f"| {r['seed']} | 0 | (no candidates) | | | | | | |")
            continue
        lines.append(
            f"| {r['seed']} | {m['n']} | {m['raw_text_median']}→{m['translated_text_median']} | "
            f"{m['magnitude_lift']:+} | {m['spearman_raw']}→{m['spearman_translated']} | "
            f"{('%+.4f' % m['agreement_lift']) if m['agreement_lift'] is not None else 'n/a'} | "
            f"{m['raw_spread']}→{m['translated_spread']} | {m['topn_overlap']} | "
            f"{'✅' if m['gate_pass'] else '❌'} |"
        )
    lines += [
        "", "## Decision", "",
        f"- seeds passing the conjunctive gate: **{len(passed)}/{len(ok)}**",
        "- A flagship that passes on a majority of vibe seeds (with the *real* translator in Phase 2) "
        "ships default-on; otherwise it stays flag-off (degrade-to-raw is the floor — cost of holding "
        "is zero).",
        "", "## β-sensitivity — can the (translated) vibe move the output, and at what fidelity cost?", "",
        "Fused top-10 vs the **pure-audio** top-10 as the vibe weight β rises (production β = **0.3**). "
        "`∩audio` 1.0 ⇒ the vibe changed nothing; `mean cos` = audio fidelity of the chosen top-10 "
        "(falls as β promotes vibe-matching-but-sonically-distant tracks).",
    ]
    for r in ok:
        curve = r.get("beta_translated")
        if not curve:
            continue
        lines += ["", f"**{r['seed']}**", "",
                  "| β | top-10 ∩ audio | mean audio-cos | min audio-cos |", "|--|--|--|--|"]
        for pt in curve:
            mark = " ← prod" if pt["beta"] == 0.3 else ""
            lines.append(
                f"| {pt['beta']}{mark} | {pt['overlap_vs_audio']} | "
                f"{pt['mean_audio_cos_topN']} | {pt['min_audio_cos_topN']} |"
            )
    lines += ["", "## Translations used", ""]
    lines += [f"- **{r['seed']}** → _{r.get('translated_vibe', '—')}_" for r in ok]
    return "\n".join(lines) + "\n"


async def main() -> None:
    p = argparse.ArgumentParser(description="Doppel v2 vibe-translation A/B harness")
    p.add_argument("--seeds", choices=list(SEED_SETS), default="full",
                   help="seed set to draw vibe seeds from (only seeds with a vibe are used)")
    p.add_argument("--real", action="store_true",
                   help="translate with the real ClaudeVibeTranslator (live LLM) instead of the "
                        "Phase-1 placeholder map — this produces the actual ship decision")
    p.add_argument("--out", default="eval/reports")
    args = p.parse_args()
    seeds = [s for s in SEED_SETS[args.seeds] if s.vibe]
    if not seeds:
        print(f"no vibe seeds in the '{args.seeds}' set — nothing to A/B")
        return

    deps = await build_deps(enqueue_job=None)
    if isinstance(deps.explainer, ClaudeExplainer):
        await deps.explainer.aclose()  # rationales aren't part of this measurement
    deps.explainer = None
    sources = [ListenBrainzClient(deps.http), LastFmClient(deps.http)]
    translator = ClaudeVibeTranslator() if args.real else None

    rows: list[dict[str, Any]] = []
    try:
        for i, seed in enumerate(seeds, 1):
            if translator is not None:
                translated, translate_fn = "", translator.translate  # live LLM per seed
            else:
                translated = _PLACEHOLDER_TRANSLATIONS.get((seed.title, seed.artist, seed.vibe or ""))
                translate_fn = None
                if translated is None:
                    print(f"[{i}/{len(seeds)}] skip {seed.label}: no placeholder translation", flush=True)
                    continue
            print(f"[{i}/{len(seeds)}] {seed.label} …", flush=True)
            row = await run_vibe_ab_seed(deps, sources, seed, translated, translate=translate_fn)
            tag = "ok" if row["ok"] else f"ERROR {row['error']}"
            print(f"    {tag}  ({row['wall_s']}s)", flush=True)
            rows.append(row)
    finally:
        if translator is not None:
            await translator.aclose()
        await close_deps(deps)

    meta = {
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed_set": args.seeds, "translation_source": "real-llm" if args.real else "phase1-placeholder",
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = out_dir / f"vibe-ab-{args.seeds}-{stamp}"
    base.with_suffix(".json").write_text(json.dumps({"meta": meta, "results": rows}, indent=2))
    report = _render_report(args.seeds, rows, meta)
    base.with_suffix(".md").write_text(report)
    print("\n" + report)
    print(f"written: {base}.md / .json")


if __name__ == "__main__":
    asyncio.run(main())
