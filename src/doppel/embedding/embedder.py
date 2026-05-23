"""CLAP embedder — Deezer preview (or raw waveform / text) → 512-dim vector.

Loads LAION-CLAP (``laion/larger_clap_music_and_speech``) and turns audio and text
into the shared 512-dim embedding space the rerank scores in. Audio is the seed and
candidate previews; text is the user's optional vibe description.

Two rules shape the implementation:

* **Ephemeral audio (project invariant #2).** A preview is streamed into memory,
  decoded in memory with PyAV, embedded, and discarded — it never touches disk and is
  never cached. :meth:`ClapEmbedder.embed_preview` is the seam the pipeline calls.
* **Lazy heavy deps.** ``torch`` / ``transformers`` / ``av`` live in the ``clap`` uv
  group and are imported *inside* the methods that need them, so importing this module
  on the API-only path doesn't require the heavy stack. The ~659 MB model (Day 0) is
  loaded once, on first use, and cached on the instance (thread-safe — embeds run in
  worker threads via ``asyncio.to_thread``); dual-load across FastAPI + ARQ is accepted
  for v1.

CLAP specifics (transformers 5.x — see CLAUDE.md / DECISIONS.md): the processor takes
``audio=`` (not ``audios=``); ``get_audio_features`` / ``get_text_features`` return an
output object whose 512-dim embedding is ``.pooler_output``. MP3 decode uses PyAV
because Deezer previews carry an ID3v2 tag that breaks libsndfile's in-memory MP3
detection (DECISIONS.md, 2026-05-21).
"""
from __future__ import annotations

import asyncio
import io
import threading
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import numpy as np
from numpy.typing import NDArray

from doppel.config import (
    ALLOWED_PREVIEW_HOST_SUFFIXES,
    CLAP_DEVICE,
    CLAP_EMBED_DIM,
    CLAP_EMBED_POOLING,
    CLAP_MODEL_ID,
    CLAP_SAMPLE_RATE,
    CLAP_TEXT_MAX_TOKENS,
    CLAP_WINDOW_SAMPLES,
    MAX_PREVIEW_BYTES,
    MAX_PREVIEW_DURATION_S,
    MAX_PREVIEW_SAMPLES,
    MAX_VIBE_TEXT_CHARS,
)

if TYPE_CHECKING:  # httpx is a core dep, but the type-only import keeps load cheap.
    import httpx


class EmbeddingError(RuntimeError):
    """An audio asset could not be embedded — undecodable bytes, or empty/silent audio.

    Distinct from an HTTP failure fetching the preview (that surfaces as the underlying
    ``httpx`` error). Raised by :func:`decode_preview` when the bytes are not decodable
    audio (truncated, non-audio, an error body served as HTTP 200), and by
    :meth:`ClapEmbedder.embed_audio` / :meth:`ClapEmbedder.embed_preview` when the audio
    is empty. The orchestration treats it as a non-embeddable asset and backfills culturally.
    """


class PreviewUrlRejected(EmbeddingError):
    """A preview URL failed validation — not https, or not an allowed provider host.

    A subclass of :class:`EmbeddingError` so the orchestration's skip/backfill path catches
    it like any other non-embeddable asset, while logs can still tell a rejected URL apart
    from a decode failure.
    """


def validate_preview_url(url: str) -> None:
    """Reject a preview URL that isn't https on an allowed provider host.

    The URL is Deezer-API-derived, not user input — but a provider response is still external
    data (and from Day 5 it is persisted then re-fetched), so the outbound target is checked
    before the request. With redirects disabled in :meth:`ClapEmbedder.embed_preview`, the
    host actually contacted always equals the one validated here, which closes the realistic
    SSRF vector without DNS/IP pinning (that is deferred — see DECISIONS.md). Raises
    :class:`PreviewUrlRejected`.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise PreviewUrlRejected(f"preview URL must be https: {url!r}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise PreviewUrlRejected(f"preview URL has no host: {url!r}")
    # Match on a dot boundary so "dzcdn.net.evil.com" / "evil-dzcdn.net" do not pass.
    if not any(host == s or host.endswith(f".{s}") for s in ALLOWED_PREVIEW_HOST_SUFFIXES):
        raise PreviewUrlRejected(f"preview host not allowed: {host!r}")


def decode_preview(mp3_bytes: bytes) -> NDArray[np.float32]:
    """Decode preview MP3 bytes → 48 kHz mono float32, fully in memory (never to disk).

    PyAV (bundled ffmpeg) rather than soundfile/librosa: Deezer previews carry a leading
    ID3v2 tag that breaks libsndfile's in-memory MP3 auto-detection (DECISIONS.md,
    2026-05-21).

    Bytes that are *not decodable audio* — a truncated download, a non-audio body, an
    error page served as HTTP 200 — raise :class:`EmbeddingError` (the pipeline's
    non-embeddable signal) rather than a raw ``av`` error, so one bad preview can be
    skipped + backfilled instead of aborting the run. Decoding also stops and raises past
    :data:`MAX_PREVIEW_DURATION_S` of audio, bounding peak memory against a decompression
    bomb. Audio that decodes but is silent / empty returns an empty array; the caller
    decides whether that's usable.
    """
    import av

    chunks: list[NDArray[np.float32]] = []
    total_samples = 0

    def _take(samples: NDArray[np.float32]) -> None:
        nonlocal total_samples
        chunks.append(samples)
        total_samples += samples.shape[0]
        if total_samples > MAX_PREVIEW_SAMPLES:
            raise EmbeddingError(
                f"preview exceeds the {MAX_PREVIEW_DURATION_S}s decode cap "
                f"(> {MAX_PREVIEW_SAMPLES} samples) — refusing to buffer it"
            )

    try:
        container = av.open(io.BytesIO(mp3_bytes))
        resampler = av.AudioResampler(format="flt", layout="mono", rate=CLAP_SAMPLE_RATE)
        try:
            for frame in container.decode(audio=0):
                for resampled in resampler.resample(frame):
                    _take(resampled.to_ndarray().reshape(-1))
            for resampled in resampler.resample(None):  # flush the resampler's buffer
                _take(resampled.to_ndarray().reshape(-1))
        finally:
            container.close()
    except (av.error.FFmpegError, ValueError) as exc:
        # FFmpegError covers invalid/truncated/non-audio data (InvalidDataError); ValueError
        # covers a container with no decodable audio stream. A genuine bug
        # (TypeError/AttributeError) — and the cap's EmbeddingError, which is neither — are
        # deliberately left to propagate.
        raise EmbeddingError(f"undecodable preview audio: {exc}") from exc
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)


def _l2_normalize_rows(matrix: NDArray[np.float32]) -> NDArray[np.float32]:
    """L2-normalize each row; a zero row stays zero (no divide-by-zero)."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0)


class ClapEmbedder:
    """Loads CLAP once (lazily, thread-safely) and embeds audio / text to 512-dim.

    Embeddings are L2-normalized, so a downstream cosine similarity is a plain dot
    product (and pgvector cosine distance is well-conditioned). Instantiate one per
    process and reuse it; the model load is the expensive part.
    """

    def __init__(self, *, model_id: str = CLAP_MODEL_ID, device: str = CLAP_DEVICE) -> None:
        self.model_id = model_id
        self.device = device
        self._model = None
        self._processor = None
        self._load_lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _ensure_loaded(self):
        """Load + cache the model/processor on first use (double-checked locking)."""
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    from transformers import ClapModel, ClapProcessor

                    self._processor = ClapProcessor.from_pretrained(self.model_id)
                    self._model = ClapModel.from_pretrained(self.model_id).to(self.device).eval()
        return self._model, self._processor

    def _pooled(self, features) -> NDArray[np.float32]:
        """Extract the 512-dim ``.pooler_output`` (transformers 5.x) → float32 ndarray."""
        out = getattr(features, "pooler_output", features)
        return out.detach().cpu().numpy().astype(np.float32)

    def _windows(self, audio: NDArray[np.float32]) -> list[NDArray[np.float32]]:
        """Slice a waveform into deterministic ≤10s windows per :data:`CLAP_EMBED_POOLING`.

        Each window is ≤ the model's input window, so the feature extractor's random crop
        (``rand_trunc``) never fires — the embedding is reproducible. ``"mean"`` returns
        every non-overlapping window (the whole clip); ``"center"`` returns just the middle
        one. A clip already within one window is returned as-is.
        """
        w = CLAP_WINDOW_SAMPLES
        if len(audio) <= w:
            return [audio]
        if CLAP_EMBED_POOLING == "center":
            start = (len(audio) - w) // 2
            return [audio[start : start + w]]
        return [audio[i : i + w] for i in range(0, len(audio), w)]

    def _embed_windows(self, windows: list[NDArray[np.float32]]) -> NDArray[np.float32]:
        """Embed ≤10s windows in one batched forward pass → ``(K, 512)`` L2-normalized."""
        import torch

        model, processor = self._ensure_loaded()
        inputs = processor(audio=list(windows), sampling_rate=CLAP_SAMPLE_RATE, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            features = model.get_audio_features(**inputs)
        return _l2_normalize_rows(self._pooled(features))

    def embed_audio(self, audio: NDArray[np.float32]) -> NDArray[np.float32]:
        """Embed a 48 kHz mono waveform → a deterministic ``(512,)`` L2-normalized vector.

        A clip longer than CLAP's 10s window is windowed and pooled per
        :data:`CLAP_EMBED_POOLING` (``"mean"`` averages every window over the whole clip,
        ``"center"`` uses the middle one), so identical audio always yields an identical
        vector — required for the cached corpus and a stable seed-vs-candidate cosine. The
        per-window vectors are pooled **weighted by each window's sample count**, so a short
        trailing remainder contributes proportionally to its duration rather than getting a
        full window's vote (a ~30s preview is three near-equal windows, so this is a no-op
        there; it keeps an off-length clip's tiny tail from dominating). A single window is
        a no-op.
        """
        audio = np.asarray(audio, dtype=np.float32)
        if audio.size == 0:
            raise EmbeddingError("cannot embed empty audio")
        windows = self._windows(audio)
        window_vecs = self._embed_windows(windows)  # (K, 512) unit rows
        weights = np.array([len(w) for w in windows], dtype=np.float64)
        pooled = (window_vecs.astype(np.float64) * weights[:, None]).sum(axis=0) / weights.sum()
        return _l2_normalize_rows(pooled.astype(np.float32)[None, :])[0]

    def embed_audios(self, audios: list[NDArray[np.float32]]) -> NDArray[np.float32]:
        """Embed a batch of waveforms → ``(N, 512)`` L2-normalized vectors.

        Each track is windowed + pooled independently (see :meth:`embed_audio`). Batching
        the model call *across* tracks is a Day-6 throughput optimization; per-track keeps
        the windowing/determinism simple here. An empty batch returns a ``(0, 512)`` array.
        """
        if not audios:
            return np.zeros((0, CLAP_EMBED_DIM), dtype=np.float32)
        return np.stack([self.embed_audio(a) for a in audios])

    def embed_text(self, text: str) -> NDArray[np.float32]:
        """Embed a vibe description into the shared CLAP space → ``(512,)`` normalized.

        The text is user-supplied (the ``/recommend`` vibe leg) and CLAP's RoBERTa encoder
        caps at :data:`CLAP_TEXT_MAX_TOKENS` tokens — and *raises* on longer input, since the
        tokenizer doesn't truncate by default — so the input is bounded: blank text raises
        ``ValueError`` (``"no vibe"`` is the caller's ``vibe_text=None`` path in
        :func:`~doppel.embedding.scoring.score_candidates`, not an empty string), the string
        is trimmed to :data:`MAX_VIBE_TEXT_CHARS` before tokenizing, and the tokens are
        truncated, so a verbose description degrades gracefully instead of crashing the
        request. CLAP's text encoder is the weaker leg on cultural/emotional phrasing
        (BRAINDUMP risk), hence the audio-dominant fusion default; an LLM caption-translation
        step is a deferred fix.
        """
        # Validate + bound *before* loading the model, so a blank or pathological vibe never
        # pays the ~659 MB load (and the offline path needs no torch).
        if not text.strip():
            raise ValueError("empty vibe text; pass vibe_text=None for no vibe")
        text = text[:MAX_VIBE_TEXT_CHARS]

        import torch

        model, processor = self._ensure_loaded()
        inputs = processor(text=[text], return_tensors="pt", padding=True,
                           truncation=True, max_length=CLAP_TEXT_MAX_TOKENS)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            features = model.get_text_features(**inputs)
        return _l2_normalize_rows(self._pooled(features))[0]

    async def embed_preview(self, url: str, client: httpx.AsyncClient) -> NDArray[np.float32]:
        """Stream a Deezer preview into memory, embed it, discard the audio.

        The URL is validated (https + an allowed host) and fetched with redirects disabled,
        so the host contacted equals the validated one (:func:`validate_preview_url`). Honors
        invariant #2: the bytes live only in memory for the decode + embed, then fall out of
        scope — nothing is written to disk. The body is *streamed* with a hard
        :data:`MAX_PREVIEW_BYTES` cap (aborting mid-download), and the decode is
        duration-capped (:data:`MAX_PREVIEW_DURATION_S`), so one oversized or pathological
        asset can't OOM the worker. Decode + inference run in worker threads so the event
        loop stays free. Raises :class:`EmbeddingError` (incl. :class:`PreviewUrlRejected`)
        if the URL is disallowed, the preview is undecodable, over a cap, or yields no audio
        (all the skip/backfill signal); propagates the ``httpx`` error if the fetch fails.
        """
        validate_preview_url(url)
        data = bytearray()
        async with client.stream("GET", url, follow_redirects=False) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                data += chunk
                if len(data) > MAX_PREVIEW_BYTES:
                    raise EmbeddingError(
                        f"preview exceeds the {MAX_PREVIEW_BYTES // (1024 * 1024)} MiB "
                        f"download cap: {url}"
                    )
        audio = await asyncio.to_thread(decode_preview, bytes(data))
        if audio.size == 0:
            raise EmbeddingError(f"preview decoded to empty audio: {url}")
        return await asyncio.to_thread(self.embed_audio, audio)
