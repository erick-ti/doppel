"""Embedder tests — offline contract checks + gated live CLAP runs.

Two tiers:

* **Offline** (merge gate): the row-normalizer is correct and zero-safe, and importing
  the embedder module does *not* eagerly pull the heavy ``clap`` deps (torch /
  transformers / av) — the "API-only path stays light" invariant. These need no model.
* **Integration** (``--run-integration`` *and* the ``clap`` group installed): load CLAP
  once and prove a real Deezer preview embeds to a deterministic, L2-normalized 512-dim
  vector, that a vibe text shares that space, and that decode yields 48 kHz mono audio.
  Self-skips when the ``clap`` group is absent so the default offline suite stays green.
"""
from __future__ import annotations

import importlib.util
import math
import subprocess
import sys

import numpy as np
import pytest

from doppel.embedding.scoring import cosine_similarity

_CLAP_INSTALLED = all(importlib.util.find_spec(m) is not None for m in ("torch", "transformers", "av"))
requires_clap = pytest.mark.skipif(
    not _CLAP_INSTALLED, reason="clap group not installed — `uv sync --group clap`"
)


# --------------------------------------------------------------------------- #
# Offline — no model required
# --------------------------------------------------------------------------- #

def test_l2_normalize_rows_unit_norm_and_zero_safe() -> None:
    from doppel.embedding.embedder import _l2_normalize_rows

    out = _l2_normalize_rows(np.array([[3.0, 4.0], [0.0, 0.0], [1.0, 0.0]], dtype=np.float32))
    assert math.isclose(float(np.linalg.norm(out[0])), 1.0, abs_tol=1e-6)  # 3-4-5 → unit
    assert np.array_equal(out[1], [0.0, 0.0])  # zero row stays zero, no NaN
    assert math.isclose(float(np.linalg.norm(out[2])), 1.0, abs_tol=1e-6)
    assert np.isfinite(out).all()


def test_importing_embedder_does_not_load_heavy_deps() -> None:
    # The lazy-import contract: a fresh interpreter importing the embedder module must
    # not have pulled torch/transformers/av — they belong to methods, not module load.
    # Run in a subprocess for a clean sys.modules regardless of what this session loaded.
    code = (
        "import sys; import doppel.embedding.embedder; "
        "leaked = [m for m in ('torch', 'transformers', 'av') if m in sys.modules]; "
        "assert not leaked, leaked"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


async def test_embed_preview_raises_embedding_error_on_empty_audio(monkeypatch) -> None:
    # A decodable-but-silent preview (empty audio) is non-embeddable → EmbeddingError,
    # surfaced before any model load. No clap group needed: decode is stubbed out.
    import httpx

    from doppel.embedding.embedder import ClapEmbedder, EmbeddingError

    monkeypatch.setattr("doppel.embedding.embedder.decode_preview", lambda _: np.zeros(0, np.float32))
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=b"x")))
    async with client:
        with pytest.raises(EmbeddingError):
            await ClapEmbedder().embed_preview("https://cdns-preview.deezer.com/x.mp3", client)


async def test_embed_preview_propagates_decode_embedding_error(monkeypatch) -> None:
    # An undecodable preview: decode_preview raises EmbeddingError, and embed_preview must
    # let it reach the caller (the skip/backfill signal) rather than swallowing it.
    import httpx

    from doppel.embedding.embedder import ClapEmbedder, EmbeddingError

    def boom(_: bytes):
        raise EmbeddingError("undecodable preview audio: bad bytes")

    monkeypatch.setattr("doppel.embedding.embedder.decode_preview", boom)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=b"x")))
    async with client:
        with pytest.raises(EmbeddingError):
            await ClapEmbedder().embed_preview("https://cdns-preview.deezer.com/x.mp3", client)


async def test_embed_preview_enforces_download_byte_cap(monkeypatch) -> None:
    # A response larger than the byte cap aborts mid-stream as EmbeddingError, before decode
    # — one oversized body can't OOM the worker. (decode must not even be reached.)
    import httpx

    from doppel.embedding.embedder import ClapEmbedder, EmbeddingError

    monkeypatch.setattr("doppel.embedding.embedder.MAX_PREVIEW_BYTES", 8)
    monkeypatch.setattr("doppel.embedding.embedder.decode_preview",
                        lambda _: pytest.fail("decode reached despite the byte cap"))
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=b"x" * 100)))
    async with client:
        with pytest.raises(EmbeddingError):
            await ClapEmbedder().embed_preview("https://cdns-preview.deezer.com/x.mp3", client)


def test_validate_preview_url_accepts_deezer_hosts() -> None:
    from doppel.embedding.embedder import validate_preview_url

    validate_preview_url("https://cdnt-preview.dzcdn.net/stream/abc.mp3")  # the real live host
    validate_preview_url("https://cdns-preview.deezer.com/stream/x.mp3")


def test_validate_preview_url_rejects_bad_scheme_and_host() -> None:
    from doppel.embedding.embedder import PreviewUrlRejected, validate_preview_url

    bad = [
        "http://cdnt-preview.dzcdn.net/x.mp3",        # not https
        "https://evil.example.com/x.mp3",             # foreign host
        "https://dzcdn.net.evil.com/x.mp3",           # suffix-as-prefix bypass attempt
        "https://evil-dzcdn.net/x.mp3",               # not a dot-boundary match
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
        "https:///nohost",                            # no host
    ]
    for url in bad:
        with pytest.raises(PreviewUrlRejected):
            validate_preview_url(url)


def test_preview_url_rejected_is_embedding_error() -> None:
    # Subclassing keeps the orchestration's `except EmbeddingError` skip/backfill path intact.
    from doppel.embedding.embedder import EmbeddingError, PreviewUrlRejected

    assert issubclass(PreviewUrlRejected, EmbeddingError)


async def test_embed_preview_rejects_disallowed_host_before_fetch(monkeypatch) -> None:
    # Validation runs before any network or decode: a foreign host is never fetched.
    import httpx

    from doppel.embedding.embedder import ClapEmbedder, PreviewUrlRejected

    monkeypatch.setattr("doppel.embedding.embedder.decode_preview",
                        lambda _: pytest.fail("decode reached despite URL rejection"))
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: pytest.fail("fetch attempted despite URL rejection"))
    )
    async with client:
        with pytest.raises(PreviewUrlRejected):
            await ClapEmbedder().embed_preview("https://evil.example.com/x.mp3", client)


def test_embed_text_blank_raises_without_loading_model() -> None:
    # "No vibe" is the caller's vibe_text=None path, not an empty string. A blank vibe is
    # rejected *before* the ~659 MB model loads — so this also runs without the clap group.
    from doppel.embedding.embedder import ClapEmbedder

    embedder = ClapEmbedder()
    for blank in ("", "   ", "\n\t"):
        with pytest.raises(ValueError):
            embedder.embed_text(blank)
    assert not embedder.is_loaded


def test_embed_audio_weights_windows_by_duration(monkeypatch) -> None:
    # A short trailing window must not get a full window's vote: duration-weighted pooling
    # keeps a full window dominant over a tiny tail. Stubs the model call — no clap group.
    from doppel.config import CLAP_WINDOW_SAMPLES
    from doppel.embedding.embedder import ClapEmbedder

    full_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    tail_vec = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    embedder = ClapEmbedder()
    # _windows(audio) → [full window (W samples), tail (10 samples)]; stub their embeddings.
    monkeypatch.setattr(embedder, "_embed_windows", lambda _w: np.array([full_vec, tail_vec]))

    pooled = embedder.embed_audio(np.zeros(CLAP_WINDOW_SAMPLES + 10, dtype=np.float32))

    # Equal-weight pooling would give cos≈0.707 with each; duration weighting keeps it ≈ full_vec.
    assert cosine_similarity(pooled, full_vec) > 0.999
    assert cosine_similarity(pooled, tail_vec) < 0.05


# --------------------------------------------------------------------------- #
# Decode error translation + caps — real PyAV, no network (clap group required)
# --------------------------------------------------------------------------- #

@requires_clap
def test_decode_preview_translates_bad_bytes_to_embedding_error() -> None:
    # Real PyAV: non-audio / empty / truncated bytes raise EmbeddingError, not a raw
    # av.error.* — so a corrupt Deezer body is a skippable asset, not a job-killer.
    from doppel.embedding.embedder import EmbeddingError, decode_preview

    for bad in (b"", b"not an mp3, just bytes" * 50, b"<html><body>error</body></html>"):
        with pytest.raises(EmbeddingError):
            decode_preview(bad)


@requires_clap
def test_decode_preview_enforces_duration_cap(monkeypatch) -> None:
    # A clip longer than the decode cap raises EmbeddingError mid-decode rather than
    # buffering it all (decompression-bomb guard). 1 s of real PCM vs a tiny sample cap.
    import io
    import wave

    from doppel.embedding.embedder import EmbeddingError, decode_preview

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48_000)
        w.writeframes(b"\x00\x00" * 48_000)  # 1.0 s of silence (48k samples)

    monkeypatch.setattr("doppel.embedding.embedder.MAX_PREVIEW_SAMPLES", 1_000)
    with pytest.raises(EmbeddingError):
        decode_preview(buf.getvalue())


# --------------------------------------------------------------------------- #
# Integration — live Deezer + real CLAP (gated + clap group required)
# --------------------------------------------------------------------------- #

@pytest.mark.integration
@requires_clap
async def test_clap_embedder_end_to_end() -> None:
    """One live model load: decode + embed a real preview, plus a vibe text."""
    import httpx

    from doppel.config import (
        CLAP_EMBED_DIM,
        CLAP_SAMPLE_RATE,
        CLAP_WINDOW_SAMPLES,
        HTTP_TIMEOUT_S,
        USER_AGENT,
    )
    from doppel.embedding.embedder import ClapEmbedder, decode_preview
    from doppel.sources.deezer import DeezerClient

    embedder = ClapEmbedder()
    assert not embedder.is_loaded  # lazy: nothing loaded until the first embed

    async with httpx.AsyncClient(
        http2=True, timeout=HTTP_TIMEOUT_S, follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        track = await DeezerClient(client).find_track("HUMBLE.", "Kendrick Lamar")
        assert track is not None and track.preview_url, "no Deezer preview for a well-known seed"

        raw = await client.get(track.preview_url)
        raw.raise_for_status()
        audio = decode_preview(raw.content)
        assert audio.ndim == 1 and audio.dtype == np.float32
        assert audio.size > CLAP_WINDOW_SAMPLES, "preview should exceed one window (exercises mean-pool)"

        # The cached-corpus contract: identical audio must embed identically.
        vec = embedder.embed_audio(audio)
        assert cosine_similarity(vec, embedder.embed_audio(audio)) > 0.99999, "embedding not deterministic"

        # The pipeline seam: stream → decode → embed → discard (invariant #2).
        preview_vec = await embedder.embed_preview(track.preview_url, client)

    text_vec = embedder.embed_text("melancholic late-night synthwave, hazy and nostalgic")
    # A >512-token vibe must truncate + embed, not crash on the RoBERTa position limit.
    long_text_vec = embedder.embed_text("ethereal melancholic late night drive " * 1000)

    assert embedder.is_loaded
    for v in (vec, preview_vec, text_vec, long_text_vec):
        assert v.shape == (CLAP_EMBED_DIM,)
        assert np.isfinite(v).all()
        assert math.isclose(float(np.linalg.norm(v)), 1.0, abs_tol=1e-4), "not L2-normalized"
    assert cosine_similarity(vec, preview_vec) > 0.99  # same bytes via the seam → same vector
    # Audio and text occupy the same CLAP space → their cosine is finite and bounded.
    assert -1.0 <= cosine_similarity(vec, text_vec) <= 1.0
