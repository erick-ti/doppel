#!/usr/bin/env python3
"""Day 0 dependency validation for Doppel — the external-dependency go/no-go.

Probes the services and the audio model the hybrid retrieve-then-rerank pipeline
depends on, measures the metrics that carry real risk, and prints a PASS / WARN /
FAIL summary that decides whether Day 1 proceeds.

Checks:
  1. Deezer preview search coverage (title+artist)        [CRITICAL — highest risk]
  2. Deezer ISRC lookup  /track/isrc:<ISRC>               (undocumented; has fallback)
  3. Deezer rate-limit behaviour under burst
  4. ListenBrainz Labs similar-recordings                 (experimental; has fallback)
  5. MusicBrainz recording search on messy strings
  6. CLAP load time / memory / single-clip embedding latency   [CRITICAL]

The ISRCs (check 2), MBIDs (checks 4/5) and preview audio (check 6) are all derived
at runtime from the seed (title, artist) pairs rather than hardcoded — so the seed
set below only needs three fields, and nothing depends on UUIDs/ISRCs being memorised.

Nothing is persisted: the Deezer preview is streamed into memory, embedded, and
discarded, per the project's ephemeral-audio rule.

Usage:
  uv run --group clap python scripts/validate_dependencies.py           # full go/no-go (incl. CLAP)
  uv run python scripts/validate_dependencies.py --skip-clap            # API-only; NOT a full go/no-go
  uv run --group clap python scripts/validate_dependencies.py --json

Exit codes: 0 = GO, 1 = NO-GO (a critical check failed), 2 = INCOMPLETE (a critical
check did not run — e.g. --skip-clap, or the CLAP group isn't installed). A skipped
critical check never reads as a passing GO.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx
from rapidfuzz import fuzz

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

DEEZER_API = "https://api.deezer.com"
LISTENBRAINZ_LABS = "https://labs.api.listenbrainz.org"
MUSICBRAINZ_API = "https://musicbrainz.org/ws/2"

# MusicBrainz requires a descriptive User-Agent with contact info, and caps at
# 1 request/second. Contact is the public repo URL (no personal address).
USER_AGENT = "Doppel/0.1.0 Day0Validation ( https://github.com/erick-ti/doppel )"
MUSICBRAINZ_MIN_INTERVAL_S = 1.1  # honour the strict 1 req/sec limit, with margin.

# ListenBrainz Labs similar-recordings is an experimental endpoint. `algorithm` selects
# the session-based model; this default favours broad recall. Alternatives differ by
# day-window and top-N-listener filtering (see --algorithm).
LISTENBRAINZ_ALGORITHM = (
    "session_based_days_9000_session_300_contribution_5_threshold_15_limit_50_skip_30"
)
LISTENBRAINZ_POLITE_DELAY_S = 0.34

# CLAP model per ROADMAP; 512-dim embeddings at 48 kHz.
CLAP_MODEL_ID = "laion/larger_clap_music_and_speech"
CLAP_EXPECTED_DIM = 512
CLAP_SAMPLE_RATE = 48_000

# Verification threshold: a candidate "matches" the seed only if both title and
# artist clear this RapidFuzz token_set_ratio (handles "feat."/suffix reordering).
MATCH_SIM_THRESHOLD = 80


@dataclass(frozen=True)
class Seed:
    genre: str
    title: str
    artist: str
    messy_title: str  # realistic messy metadata variant, to test MusicBrainz tolerance


SEED_TRACKS: list[Seed] = [
    Seed("pop", "Blinding Lights", "The Weeknd", "Blinding Lights (Remaster)"),
    Seed("hip-hop", "HUMBLE.", "Kendrick Lamar", "HUMBLE"),
    Seed("indie", "The Less I Know the Better", "Tame Impala",
         "The Less I Know The Better - Edit"),
    Seed("electronic", "One More Time", "Daft Punk", "One More Time (feat. Romanthony)"),
    Seed("jazz", "Take Five", "The Dave Brubeck Quartet", "Take Five (Remastered)"),
]


# --------------------------------------------------------------------------- #
# Result model
# --------------------------------------------------------------------------- #

class Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


SYMBOL = {Status.PASS: "✓", Status.WARN: "⚠", Status.FAIL: "✗", Status.SKIP: "–"}


@dataclass
class CheckResult:
    number: int
    name: str
    status: Status
    summary: str
    critical: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)


def _status_from_fraction(good: int, total: int, *, pass_at: int, warn_at: int) -> Status:
    """PASS at >= pass_at, WARN at >= warn_at, else FAIL (total==0 -> WARN)."""
    if total == 0:
        return Status.WARN
    if good >= pass_at:
        return Status.PASS
    if good >= warn_at:
        return Status.WARN
    return Status.FAIL


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

_PARENTHETICAL = re.compile(r"\s*[\(\[].*?[\)\]]\s*")
_DASH_SUFFIX = re.compile(r"\s+-\s+.*$")


def strip_title_noise(title: str) -> str:
    """Drop parenthetical/bracketed and ' - <suffix>' noise for a relaxed query.

    For *querying* a search backend only. The real matcher's dedupe must PRESERVE
    variant tokens (live/remaster/acoustic/etc.) to distinguish recordings (the
    matcher does a conservative dedupe). This strips them solely to widen a search
    that an exact-phrase query missed; disambiguation then happens via duration/ISRC.
    """
    cleaned = _PARENTHETICAL.sub(" ", title)
    cleaned = _DASH_SUFFIX.sub("", cleaned)
    return " ".join(cleaned.split()).strip()


def _artist_credit_name(rec: dict) -> str:
    return (rec.get("artist-credit") or [{}])[0].get("name", "")


def _sims(title: str, artist: str, cand_title: str, cand_artist: str) -> tuple[float, float]:
    return (fuzz.token_set_ratio(title, cand_title), fuzz.token_set_ratio(artist, cand_artist))


_mb_next_allowed = 0.0


async def mb_recording_search(client: httpx.AsyncClient, title: str, artist: str,
                              limit: int = 5) -> list[dict]:
    """MusicBrainz recording search (exact-phrase title + artist), self-paced ≤1 req/sec."""
    global _mb_next_allowed
    wait = _mb_next_allowed - time.monotonic()
    if wait > 0:
        await asyncio.sleep(wait)
    _mb_next_allowed = time.monotonic() + MUSICBRAINZ_MIN_INTERVAL_S
    r = await client.get(
        f"{MUSICBRAINZ_API}/recording",
        params={"query": f'recording:"{title}" AND artist:"{artist}"', "fmt": "json", "limit": limit},
        headers={"User-Agent": USER_AGENT},
    )
    r.raise_for_status()
    return r.json().get("recordings", [])


# --------------------------------------------------------------------------- #
# Check 1 — Deezer preview search coverage  (CRITICAL)
# --------------------------------------------------------------------------- #

async def check_deezer_search(
    client: httpx.AsyncClient, seeds: list[Seed]
) -> tuple[CheckResult, dict[str, dict]]:
    resolved: dict[str, dict] = {}
    details: list[str] = []
    covered = 0

    for seed in seeds:
        # Advanced field-scoped query first; fall back to a plain query if it whiffs.
        data: list[dict] = []
        for q in (f'artist:"{seed.artist}" track:"{seed.title}"', f"{seed.artist} {seed.title}"):
            try:
                r = await client.get(f"{DEEZER_API}/search", params={"q": q})
                r.raise_for_status()
                data = r.json().get("data", [])
            except Exception as exc:  # noqa: BLE001 - report, don't crash the run
                details.append(f"  {seed.genre:11} {seed.artist} – {seed.title}: ERROR {exc!r}")
                data = []
            if data:
                break
        if not data:
            details.append(f"  {seed.genre:11} {seed.artist} – {seed.title}: no result")
            continue

        top = data[0]
        hit_title = top.get("title", "")
        hit_artist = top.get("artist", {}).get("name", "")
        preview = top.get("preview") or ""
        title_sim, artist_sim = _sims(seed.title, seed.artist, hit_title, hit_artist)
        verified = title_sim >= MATCH_SIM_THRESHOLD and artist_sim >= MATCH_SIM_THRESHOLD
        is_covered = bool(preview) and verified
        if is_covered:
            covered += 1

        resolved[seed.genre] = {
            "seed": seed,
            "track_id": top.get("id"),
            "title": hit_title,
            "artist": hit_artist,
            "preview": preview,
            "full_duration_s": top.get("duration"),
            "verified": verified,
        }
        flags = ("preview✓" if preview else "NO-PREVIEW") + ("/verified" if verified else "/LOW-SIM")
        details.append(
            f"  {seed.genre:11} → {hit_artist} – {hit_title} "
            f"[{flags}, full dur {top.get('duration')}s, sim t{title_sim:.0f}/a{artist_sim:.0f}]"
        )

    n = len(seeds)
    status = _status_from_fraction(covered, n, pass_at=4, warn_at=3)
    summary = f"{covered}/{n} seeds resolved to a verified track with a usable preview ({covered / n:.0%})"
    return (
        CheckResult(1, "Deezer preview search coverage", status, summary, critical=True,
                    metrics={"covered": covered, "total": n, "coverage": round(covered / n, 2)},
                    details=details),
        resolved,
    )


# --------------------------------------------------------------------------- #
# Check 2 — Deezer ISRC lookup  (undocumented endpoint)
# --------------------------------------------------------------------------- #

async def check_deezer_isrc(client: httpx.AsyncClient, resolved: dict[str, dict]) -> CheckResult:
    details: list[str] = []
    tried = 0
    ok = 0

    for genre, info in resolved.items():
        tid = info.get("track_id")
        if not tid:
            continue
        # Search results omit ISRC; read it from the full track object, then round-trip
        # it through the undocumented /track/isrc: endpoint.
        try:
            r = await client.get(f"{DEEZER_API}/track/{tid}")
            r.raise_for_status()
            isrc = r.json().get("isrc")
        except Exception as exc:  # noqa: BLE001
            details.append(f"  {genre:11} /track/{tid}: ERROR {exc!r}")
            continue
        if not isrc:
            details.append(f"  {genre:11} /track/{tid}: no ISRC field")
            continue

        tried += 1
        try:
            body = (await client.get(f"{DEEZER_API}/track/isrc:{isrc}")).json()
        except Exception as exc:  # noqa: BLE001
            details.append(f"  {genre:11} isrc:{isrc}: ERROR {exc!r}")
            continue
        if isinstance(body, dict) and body.get("error"):
            details.append(f"  {genre:11} isrc:{isrc}: error {body['error']}")
            continue

        ok += 1
        returned_id = body.get("id")
        # id≠ is expected/fine: an ISRC can map to multiple Deezer releases of the same recording.
        match = "id✓" if returned_id == tid else f"id≠ ({returned_id} vs {tid}; same ISRC, other release)"
        details.append(f"  {genre:11} isrc:{isrc} → track {returned_id} [{match}]")

    works = ok == tried and tried > 0
    status = Status.WARN if tried == 0 else (Status.PASS if works else Status.WARN if ok else Status.FAIL)
    if tried == 0:
        summary = "no ISRCs available to test (upstream search yielded none)"
    elif ok == 0:
        summary = f"0/{tried} resolved — endpoint appears dead; set DEEZER_ISRC_ENABLED=false, use search+verify"
    else:
        summary = f"{ok}/{tried} ISRC lookups resolved — endpoint works ({'reliable' if works else 'flaky'})"
    return CheckResult(2, "Deezer ISRC lookup (/track/isrc:)", status, summary,
                       metrics={"tried": tried, "ok": ok, "recommend_DEEZER_ISRC_ENABLED": works},
                       details=details)


# --------------------------------------------------------------------------- #
# Check 3 — Deezer rate-limit behaviour under burst
# --------------------------------------------------------------------------- #

async def check_deezer_rate_limit(
    client: httpx.AsyncClient, resolved: dict[str, dict], burst: int
) -> CheckResult:
    tid = next((i["track_id"] for i in resolved.values() if i.get("track_id")), None)

    async def one(_: int) -> tuple[str, int | None, Any]:
        try:
            if tid:
                r = await client.get(f"{DEEZER_API}/track/{tid}")
            else:
                r = await client.get(f"{DEEZER_API}/search", params={"q": "jazz"})
            body = r.json()
            err = body.get("error") if isinstance(body, dict) else None
            if r.status_code == 429 or (err and err.get("code") in (4, 700)):
                return ("throttled", r.status_code, err)
            if err:
                return ("error", r.status_code, err)
            return ("ok", r.status_code, None)
        except Exception as exc:  # noqa: BLE001
            return ("error", None, repr(exc))

    t0 = time.perf_counter()
    results = await asyncio.gather(*(one(i) for i in range(burst)))
    elapsed = time.perf_counter() - t0
    await asyncio.sleep(5)  # cooldown so the burst doesn't bleed into nothing downstream

    ok = sum(1 for s, *_ in results if s == "ok")
    throttled = sum(1 for s, *_ in results if s == "throttled")
    errored = sum(1 for s, *_ in results if s == "error")
    attempted_rate = burst / elapsed if elapsed else 0.0

    details = [
        f"  fired {burst} concurrent requests in {elapsed:.2f}s (~{attempted_rate:.0f} req/s attempted)",
        f"  ok={ok}  throttled={throttled}  error={errored}",
    ]
    sample = next((payload for s, _, payload in results if s != "ok"), None)
    if sample is not None:
        details.append(f"  sample non-ok payload: {sample}")

    # Provisioned at ~45 req/5s (~9/s sustained). A burst tripping a graceful quota error
    # is the healthy outcome; hard errors / connection failures are the worrying one.
    if errored and errored >= throttled:
        status, summary = Status.WARN, f"{ok}/{burst} ok but {errored} hard errors — investigate failure mode"
    elif throttled:
        status, summary = Status.PASS, f"{ok}/{burst} ok, {throttled} throttled — quota enforced gracefully; honour ≤45 req/5s"
    else:
        status, summary = Status.PASS, f"all {ok}/{burst} succeeded — no throttling seen at this burst (limit not reached)"
    return CheckResult(3, "Deezer rate-limit under burst", status, summary,
                       metrics={"burst": burst, "ok": ok, "throttled": throttled,
                                "errored": errored, "elapsed_s": round(elapsed, 2)},
                       details=details)


# --------------------------------------------------------------------------- #
# Check 5 — MusicBrainz recording search on messy strings
# --------------------------------------------------------------------------- #

async def check_musicbrainz(client: httpx.AsyncClient, seeds: list[Seed]) -> CheckResult:
    details: list[str] = []
    matched = 0

    for seed in seeds:
        # Stage 1: exact phrase on the messy title. Stage 2 (if empty): relaxed query on the
        # noise-stripped title. Mirrors how the matcher will canonicalise messy upstream strings.
        stage = "exact"
        try:
            recs = await mb_recording_search(client, seed.messy_title, seed.artist)
            if not recs:
                cleaned = strip_title_noise(seed.messy_title)
                recs = await mb_recording_search(client, cleaned, seed.artist)
                stage = f"relaxed('{cleaned}')"
        except Exception as exc:  # noqa: BLE001
            details.append(f"  {seed.genre:11} messy='{seed.messy_title}': ERROR {exc!r}")
            continue
        if not recs:
            details.append(f"  {seed.genre:11} messy='{seed.messy_title}': no recordings (both stages)")
            continue

        # Pick the best of the top hits by similarity to the CLEAN seed.
        def score(rec: dict) -> tuple[float, float]:
            return _sims(seed.title, seed.artist, rec.get("title", ""), _artist_credit_name(rec))

        best = max(recs[:5], key=lambda rec: sum(score(rec)))
        t_sim, a_sim = score(best)
        verified = t_sim >= MATCH_SIM_THRESHOLD and a_sim >= MATCH_SIM_THRESHOLD
        if verified:
            matched += 1
        details.append(
            f"  {seed.genre:11} messy='{seed.messy_title}' [{stage}] → "
            f"{_artist_credit_name(best)} – {best.get('title')} "
            f"(score {best.get('score')}, sim t{t_sim:.0f}/a{a_sim:.0f}) "
            f"{'✓verified' if verified else '✗low-sim'} mbid={best['id'][:8]}…"
        )

    n = len(seeds)
    status = _status_from_fraction(matched, n, pass_at=4, warn_at=3)
    summary = f"{matched}/{n} messy queries canonicalised to the correct recording (2-stage query)"
    return CheckResult(5, "MusicBrainz messy-string search", status, summary,
                       metrics={"matched": matched, "total": n}, details=details)


# --------------------------------------------------------------------------- #
# Check 4 — ListenBrainz Labs similar-recordings  (experimental)
# --------------------------------------------------------------------------- #

async def lb_resolve_canonical_mbid(client: httpx.AsyncClient, seed: Seed) -> str | None:
    """Resolve a seed to a ListenBrainz-canonical recording MBID via the Labs recording-search
    dataset. similar-recordings is keyed on these canonical MBIDs — arbitrary MusicBrainz
    recording MBIDs do NOT match it (validated Day 0)."""
    r = await client.get(f"{LISTENBRAINZ_LABS}/recording-search/json",
                         params={"query": f"{seed.title} {seed.artist}"})
    r.raise_for_status()
    rows = r.json() if r.text.lstrip().startswith("[") else []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        t_sim, a_sim = _sims(seed.title, seed.artist,
                             row.get("recording_name", ""), row.get("artist_credit_name", ""))
        if t_sim >= MATCH_SIM_THRESHOLD and a_sim >= MATCH_SIM_THRESHOLD:
            return row.get("recording_mbid")
    return None


async def check_listenbrainz(
    client: httpx.AsyncClient, seeds: list[Seed], algorithm: str
) -> CheckResult:
    details: list[str] = []
    resolved = 0
    nonempty = 0
    yields: list[int] = []
    fields_seen: set[str] = set()

    for i, seed in enumerate(seeds):
        if i:
            await asyncio.sleep(LISTENBRAINZ_POLITE_DELAY_S)
        try:
            mbid = await lb_resolve_canonical_mbid(client, seed)
        except Exception as exc:  # noqa: BLE001
            details.append(f"  {seed.genre:11}: recording-search ERROR {exc!r}")
            continue
        if not mbid:
            details.append(f"  {seed.genre:11}: no canonical MBID from recording-search")
            continue
        resolved += 1

        await asyncio.sleep(LISTENBRAINZ_POLITE_DELAY_S)
        try:
            r = await client.get(f"{LISTENBRAINZ_LABS}/similar-recordings/json",
                                 params={"recording_mbids": mbid, "algorithm": algorithm})
            r.raise_for_status()
            rows = r.json() if r.text.lstrip().startswith("[") else []
        except Exception as exc:  # noqa: BLE001
            details.append(f"  {seed.genre:11} mbid={mbid[:8]}…: similar-recordings ERROR {exc!r}")
            continue

        count = len(rows) if isinstance(rows, list) else 0
        if count:
            nonempty += 1
            yields.append(count)
            if isinstance(rows[0], dict):
                fields_seen.update(rows[0].keys())
        details.append(f"  {seed.genre:11} mbid={mbid[:8]}… → {count} similar recordings")

    n = len(seeds)
    # Experimental endpoint + thin listen data for older/niche genres ⇒ some empties expected.
    status = _status_from_fraction(nonempty, n, pass_at=4, warn_at=2)
    avg = (sum(yields) / len(yields)) if yields else 0.0
    summary = (f"{nonempty}/{n} seeds returned similar recordings "
               f"(resolved {resolved}/{n} canonical MBIDs, avg yield {avg:.0f})")
    if fields_seen:
        details.append(f"  response row fields: {sorted(fields_seen)}")
    return CheckResult(4, "ListenBrainz Labs similar-recordings", status, summary,
                       metrics={"resolved": resolved, "nonempty": nonempty,
                                "avg_yield": round(avg, 1), "algorithm": algorithm},
                       details=details)


# --------------------------------------------------------------------------- #
# Check 6 — CLAP load / memory / latency  (CRITICAL)
# --------------------------------------------------------------------------- #

def _decode_mp3_48k_mono(mp3_bytes: bytes):
    """Decode MP3 preview bytes → 48 kHz mono float32, fully in memory (never to disk).

    PyAV (bundled ffmpeg) is used rather than soundfile/librosa: Deezer previews carry a
    leading ID3v2 tag that breaks libsndfile's in-memory MP3 auto-detection (validated Day 0;
    decoding from a file PATH works, but the project's ephemeral-audio rule forbids disk).
    """
    import av
    import numpy as np

    container = av.open(io.BytesIO(mp3_bytes))
    resampler = av.AudioResampler(format="flt", layout="mono", rate=CLAP_SAMPLE_RATE)
    chunks: list[np.ndarray] = []
    try:
        for frame in container.decode(audio=0):
            for resampled in resampler.resample(frame):
                chunks.append(resampled.to_ndarray().reshape(-1))
        for resampled in resampler.resample(None):  # flush the resampler
            chunks.append(resampled.to_ndarray().reshape(-1))
    finally:
        container.close()
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)


async def check_clap(client: httpx.AsyncClient, resolved: dict[str, dict], device: str) -> CheckResult:
    try:
        import av  # noqa: F401 — used by _decode_mp3_48k_mono
        import psutil
        import torch
        from transformers import ClapModel, ClapProcessor
    except ImportError as exc:
        return CheckResult(6, "CLAP load/memory/latency", Status.SKIP,
                           f"CLAP deps not installed ({exc.name}) — `uv sync --group clap`, then rerun",
                           critical=True)

    preview = next((i["preview"] for i in resolved.values() if i.get("preview")), None)
    if not preview:
        return CheckResult(6, "CLAP load/memory/latency", Status.WARN,
                           "no Deezer preview available to embed (upstream coverage failed)",
                           critical=True)

    try:
        proc = psutil.Process()
        rss_before = proc.memory_info().rss

        t0 = time.perf_counter()
        model = ClapModel.from_pretrained(CLAP_MODEL_ID)
        processor = ClapProcessor.from_pretrained(CLAP_MODEL_ID)
        model = model.to(device).eval()
        load_s = time.perf_counter() - t0
        rss_after_load = proc.memory_info().rss

        resp = await client.get(preview)
        resp.raise_for_status()
        audio = await asyncio.to_thread(_decode_mp3_48k_mono, resp.content)

        def embed():
            inputs = processor(audio=[audio], sampling_rate=CLAP_SAMPLE_RATE, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            with torch.no_grad():
                out = model.get_audio_features(**inputs)
            # transformers 5.x returns an output object; the 512-dim audio embedding is pooler_output.
            return getattr(out, "pooler_output", out)

        await asyncio.to_thread(embed)  # warm-up (first call pays one-time costs)
        t1 = time.perf_counter()
        feats = await asyncio.to_thread(embed)
        embed_ms = (time.perf_counter() - t1) * 1000
        dim = int(feats.shape[-1])

        rss_peak = proc.memory_info().rss
        model_mb = (rss_after_load - rss_before) / 1e6
        peak_mb = rss_peak / 1e6
    except Exception as exc:  # noqa: BLE001
        return CheckResult(6, "CLAP load/memory/latency", Status.FAIL,
                           f"CLAP check raised: {exc!r}", critical=True)

    details = [
        f"  model: {CLAP_MODEL_ID} on {device}",
        f"  load time: {load_s:.1f}s",
        f"  model memory (RSS delta over torch baseline): {model_mb:.0f} MB",
        f"  process RSS after embed: {peak_mb:.0f} MB  (dual-load ≈ {2 * peak_mb:.0f} MB)",
        f"  embedding latency (warm): {embed_ms:.0f} ms",
        f"  embedding dim: {dim} (expected {CLAP_EXPECTED_DIM})",
    ]
    if dim != CLAP_EXPECTED_DIM:
        status = Status.FAIL
    elif peak_mb > 1800 or embed_ms > 2000 or load_s > 90:
        status = Status.WARN
    else:
        status = Status.PASS
    summary = f"loaded {load_s:.0f}s, ~{peak_mb:.0f}MB process RSS, embed {embed_ms:.0f}ms, dim {dim}"
    return CheckResult(6, "CLAP load/memory/latency", status, summary, critical=True,
                       metrics={"load_s": round(load_s, 1), "model_mb": round(model_mb),
                                "process_rss_mb": round(peak_mb), "embed_ms": round(embed_ms),
                                "dim": dim, "device": device},
                       details=details)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def emit(r: CheckResult) -> None:
    tag = "  (critical)" if r.critical else ""
    print(f"\n[{SYMBOL[r.status]}] Check {r.number}: {r.name} — {r.status.value}{tag}")
    print(f"    {r.summary}")
    for line in r.details:
        print(line)


def compute_verdict(results: list[CheckResult], *, api_only: bool = False) -> tuple[str, int]:
    """Decide the overall verdict and process exit code from the check results.

    Exit codes:
      0  GO          — every critical check ran and passed (non-critical issues at most)
      1  NO-GO       — a critical check FAILED
      2  INCOMPLETE  — a critical check did not run (SKIP); the go/no-go is undecided

    A critical SKIP must never read as a passing GO: skipping the CLAP gate (via
    --skip-clap or because the CLAP deps aren't installed) leaves the pipeline's
    audio-scoring leg unvalidated, so it cannot bless the architecture.
    """
    fails = [r for r in results if r.status == Status.FAIL]
    warns = [r for r in results if r.status == Status.WARN]
    skips = [r for r in results if r.status == Status.SKIP]
    crit_fails = [r for r in fails if r.critical]
    crit_skips = [r for r in skips if r.critical]

    if crit_fails:
        return "NO-GO — a critical dependency failed", 1
    if crit_skips:
        which = ", ".join(f"Check {r.number} ({r.name})" for r in crit_skips)
        if api_only:
            return f"INCOMPLETE (API-only run) — critical {which} intentionally skipped; not a full go/no-go", 2
        return f"INCOMPLETE — critical {which} did not run (install the CLAP group, then rerun); not a full go/no-go", 2
    if fails:
        return "GO WITH CAVEATS — non-critical failures (have fallbacks)", 0
    if warns or skips:
        noted = " and ".join(
            label for label, present in (("warnings", warns), ("skipped non-critical checks", skips)) if present
        )
        return f"GO — with {noted} noted", 0
    return "GO — all dependencies validated", 0


def summarize(results: list[CheckResult], *, as_json: bool, api_only: bool = False) -> int:
    print("\n" + "=" * 74)
    print(" SUMMARY")
    print("=" * 74)
    for r in results:
        crit = "*" if r.critical else " "
        print(f" {SYMBOL[r.status]} {r.status.value:4} {crit} Check {r.number}: {r.name}")
        print(f"           {r.summary}")

    verdict, code = compute_verdict(results, api_only=api_only)

    print("\n" + "-" * 74)
    print(f" VERDICT: {verdict}")
    print(" (* = critical: Deezer coverage and CLAP gate the whole pipeline)")
    print("-" * 74)

    if as_json:
        payload = {
            "verdict": verdict,
            "exit_code": code,
            "checks": [
                {"number": r.number, "name": r.name, "status": r.status.value,
                 "critical": r.critical, "summary": r.summary, "metrics": r.metrics}
                for r in results
            ],
        }
        print("\nJSON:\n" + json.dumps(payload, indent=2))
    return code


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

async def run(args: argparse.Namespace) -> int:
    results: list[CheckResult] = []
    timeout = httpx.Timeout(args.timeout)
    limits = httpx.Limits(max_connections=max(20, args.deezer_burst + 10))

    mode = "  [API-ONLY MODE — CLAP not run]" if args.skip_clap else ""
    print("=" * 74)
    print(" Doppel — Day 0 external dependency validation" + mode)
    print("=" * 74)

    async with httpx.AsyncClient(http2=True, timeout=timeout, limits=limits,
                                 headers={"User-Agent": USER_AGENT},
                                 follow_redirects=True) as client:
        # Order driven by data flow: search feeds ISRC + CLAP; the burst runs after the
        # cheap Deezer calls. Checks 4 and 5 are independent (each does its own resolution).
        r1, resolved = await check_deezer_search(client, SEED_TRACKS)
        emit(r1); results.append(r1)

        r2 = await check_deezer_isrc(client, resolved)
        emit(r2); results.append(r2)

        r5 = await check_musicbrainz(client, SEED_TRACKS)
        emit(r5); results.append(r5)

        r4 = await check_listenbrainz(client, SEED_TRACKS, args.algorithm)
        emit(r4); results.append(r4)

        r3 = await check_deezer_rate_limit(client, resolved, args.deezer_burst)
        emit(r3); results.append(r3)

        if args.skip_clap:
            r6 = CheckResult(6, "CLAP load/memory/latency", Status.SKIP,
                             "skipped (--skip-clap)", critical=True)
        else:
            r6 = await check_clap(client, resolved, args.clap_device)
        emit(r6); results.append(r6)

    return summarize(sorted(results, key=lambda r: r.number), as_json=args.json, api_only=args.skip_clap)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Doppel Day 0 external dependency validation")
    p.add_argument("--skip-clap", action="store_true",
                   help="API-ONLY mode: skip the critical CLAP check. NOT a full go/no-go "
                        "(verdict will be INCOMPLETE, exit 2).")
    p.add_argument("--clap-device", default="cpu", choices=["cpu", "mps", "cuda"],
                   help="device for CLAP (default cpu — representative of the VPS target)")
    p.add_argument("--deezer-burst", type=int, default=60,
                   help="concurrent requests for the rate-limit probe (default 60)")
    p.add_argument("--algorithm", default=LISTENBRAINZ_ALGORITHM, help="ListenBrainz similar-recordings algorithm")
    p.add_argument("--timeout", type=float, default=30.0, help="per-request timeout in seconds")
    p.add_argument("--json", action="store_true", help="also print a machine-readable JSON summary")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    try:
        sys.exit(asyncio.run(run(args)))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
